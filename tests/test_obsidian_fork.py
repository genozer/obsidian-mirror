# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Tests for what the Obsidian Mirror fork added: Thai/English text, picture splitting,
the OBS Browser Source stream and graphics-card decoding (no iPhone needed)."""
from __future__ import annotations

import ast
import json
import re
import socket
import struct
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from app import i18n
from app.video_stream import H264Decoder, VideoServer, frame_to_qimage, scaled_size
from app.web_source import MAGIC, MSG_AU, MSG_END, AccessUnitSplitter, StreamHub, WebSource

APP = Path(__file__).resolve().parent.parent / "app"


def make_h264(width=320, height=640, frames=30, gop=10) -> bytes:
    enc = av.CodecContext.create("libx264", "w")
    enc.width, enc.height, enc.pix_fmt = width, height, "yuv420p"
    enc.time_base = Fraction(1, 30)
    enc.framerate = Fraction(30, 1)
    enc.gop_size = gop
    enc.options = {"bf": "0", "sc_threshold": "0"}   # key frames exactly every `gop`
    out = bytearray()
    for i in range(frames):
        img = np.full((height, width, 3), (i * 20) % 255, dtype=np.uint8)
        img[(i * 10) % height:(i * 10) % height + 20, :, 1] = 255
        frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")
        frame.pts = i
        for pkt in enc.encode(frame):
            out += bytes(pkt)
    for pkt in enc.encode(None):
        out += bytes(pkt)
    return bytes(out)


@pytest.fixture(scope="module")
def stream() -> bytes:
    return make_h264()


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


# --- language ----------------------------------------------------------------------------
def _t_literals() -> set[str]:
    found = set()
    for path in APP.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "T" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    # Texts kept in tables and translated through T(variable).
    from app.common_actions import FPS_CHOICES, LANGUAGE_NAMES, MODE_NAMES, PREVIEW_MODES, SOURCE_NAMES
    from app.lock_screen import ANDROID_STEPS, HINT, LINK_TITLES, OTHER_PHONE, STEPS, SUBTITLES, TITLES
    from app.main_window import COLOR_NAMES
    from app.plain_window import FIT_INFO
    found |= set(TITLES.values()) | set(LINK_TITLES.values()) | set(SUBTITLES.values())
    found |= set(STEPS) | set(ANDROID_STEPS) | {HINT} | set(MODE_NAMES.values()) | set(OTHER_PHONE.values())
    found |= set(COLOR_NAMES.values()) | {v[1] for v in FIT_INFO.values()}
    found |= {v for k, v in LANGUAGE_NAMES.items() if k == "auto"} | set(FPS_CHOICES.values()) | set(PREVIEW_MODES.values())
    found |= set(SOURCE_NAMES.values())
    from app.wifi_dialog import FAILED, STATUS, STEPS_TEXT
    found |= {STEPS_TEXT} | set(STATUS.values()) | set(FAILED.values())
    from app.update_dialog import ERRORS
    found |= set(ERRORS)
    from app.common_actions import CAMERA_HELP, CAMERA_NAMES
    found |= {CAMERA_HELP} | set(CAMERA_NAMES.values()) | {"the camera is in use by another program"}
    from app.common_actions import CAMERA_SOURCE_NAMES
    from app.phone_cam_dialog import STATES
    from app.phone_cam_dialog import STEPS_TEXT as PHONE_STEPS
    found |= set(CAMERA_SOURCE_NAMES.values()) | {v[0] for v in STATES.values()} | {PHONE_STEPS}
    return found


def test_every_text_has_thai():
    missing = sorted(t for t in _t_literals() if t not in i18n.TH)
    assert not missing, f"no Thai for: {missing}"


def test_no_russian_left_in_what_users_see():
    cyr = re.compile("[А-Яа-яЁё]")
    for path in APP.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        # log.* messages go to the developer console only; everything else reaches users.
        dev_only = {id(c) for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and getattr(n.func.value, "id", None) == "log"
                    for c in ast.walk(n)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and id(node) not in dev_only):
                # The original author's name in the credits is meant to stay.
                if cyr.search(node.value) and "Сорокин" not in node.value:
                    raise AssertionError(f"{path.name}:{node.lineno} {node.value!r}")


def test_thai_placeholders_match_english():
    for en, th in i18n.TH.items():
        if en == "USB_HELP":
            continue
        assert set(re.findall(r"{\w+}", en)) == set(re.findall(r"{\w+}", th)), en


def test_language_switch_and_dates():
    i18n.set_language("th")
    try:
        assert i18n.T("Restart receiver") == "เริ่มตัวรับภาพใหม่"
        assert i18n.date_line(4, 19, 11) == "วันศุกร์ที่ 19 พฤศจิกายน"
    finally:
        i18n.set_language("en")
    assert i18n.T("Restart receiver") == "Restart receiver"
    assert i18n.date_line(0, 1, 1) == "Monday, 1 January"
    assert i18n.T("not in the table") == "not in the table"


# --- splitting into pictures -----------------------------------------------------------
def test_splitter_gives_every_picture_whatever_the_chunk_size(stream):
    for chunk in (1, 7, 1000, len(stream)):
        sp = AccessUnitSplitter()
        aus = []
        for i in range(0, len(stream), chunk):
            aus += sp.feed(stream[i:i + chunk])
        aus += sp.finish()
        assert len(aus) == 30, chunk
        assert [k for _, k in aus].count(True) == 3      # gop 10 → 3 key frames
        assert aus[0][1] is True


def test_pictures_decode_one_by_one_without_delay(stream):
    sp = AccessUnitSplitter()
    aus = sp.feed(stream) + sp.finish()
    dec = H264Decoder(use_gpu=False)
    counts = [len(dec.decode_au(au)) for au, _ in aus]
    assert counts == [1] * 30      # each picture comes out at once (no parser delay)


# --- conversion size ---------------------------------------------------------------------
def test_scaled_size_shrinks_only():
    assert scaled_size(1180, 2556, (0, 0, False)) == (1180, 2556)
    assert scaled_size(1180, 2556, (590, 2000, False)) == (590, 1278)
    assert scaled_size(1180, 2556, (590, 2000, True)) == (924, 2000)
    assert scaled_size(320, 640, (2000, 2000, False)) == (320, 640)


# --- graphics-card decoding ----------------------------------------------------------------
def test_gpu_decoder_matches_cpu(stream):
    gpu = H264Decoder(use_gpu=True)
    if gpu.kind != "gpu":
        pytest.skip("no D3D11 device on this machine")
    cpu = H264Decoder(use_gpu=False)
    sp = AccessUnitSplitter()
    aus = sp.feed(stream) + sp.finish()
    g = [f for au, _ in aus for f in gpu.decode_au(au)]
    c = [f for au, _ in aus for f in cpu.decode_au(au)]
    assert len(g) == len(c) == 30
    a = frame_to_qimage(g[-1])
    b = frame_to_qimage(c[-1])
    assert (a.width(), a.height()) == (b.width(), b.height()) == (320, 640)
    # Same picture (colour conversion may differ by a few levels).
    pa = np.frombuffer(a.constBits(), np.uint8)[: a.sizeInBytes()].astype(int)
    pb = np.frombuffer(b.constBits(), np.uint8)[: b.sizeInBytes()].astype(int)
    assert np.abs(pa - pb).mean() < 4


# --- OBS stream ------------------------------------------------------------------------
def _read_messages(raw: bytes):
    assert raw[:4] == MAGIC
    off, out = 4, []
    while off + 6 <= len(raw):
        kind, flags, length = struct.unpack(">BBI", raw[off:off + 6])
        if off + 6 + length > len(raw):
            break
        out.append((kind, flags, raw[off + 6:off + 6 + length]))
        off += 6 + length
    return out


def test_late_viewer_gets_pictures_since_last_key_frame(stream):
    hub = StreamHub()
    sp = AccessUnitSplitter()
    aus = sp.feed(stream) + sp.finish()
    hub.feed(1, aus[:15])          # key frames at 0 and 10 → replay = pictures 10..14
    c = hub.subscribe()
    got = [c.q.get_nowait() for _ in range(c.q.qsize())]
    assert len(got) == 5
    assert got[0][1] & 1 == 1      # starts with the key frame
    hub.feed(1, aus[15:16])
    assert c.q.qsize() == 1
    hub.end(1)
    assert c.q.get_nowait()[1:2] and c.q.get_nowait()[0] == MSG_END


def test_newer_connection_wins(stream):
    hub = StreamHub()
    sp = AccessUnitSplitter()
    aus = sp.feed(stream) + sp.finish()
    hub.feed(1, aus[:3])
    hub.feed(2, aus[:2])
    hub.feed(1, aus[3:4])           # old connection still trickling: ignored
    assert hub.status()["pictures"] == 5


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_page_status_and_stream_end_to_end(qapp, stream):
    web = WebSource(_free_port())
    assert web.start()
    vport = _free_port()
    server = VideoServer(vport, use_gpu=False)
    server.sink, server.sink_end = web.hub.feed, web.hub.end
    server.start()
    try:
        page = urllib.request.urlopen(web.url, timeout=5).read().decode()
        assert "VideoDecoder" in page and "<canvas" in page
        resp = urllib.request.urlopen(f"http://127.0.0.1:{web.port}/stream", timeout=5)
        deadline = time.time() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", vport), timeout=1) as s:
                    s.sendall(stream)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        raw = b""
        deadline = time.time() + 5
        while time.time() < deadline:
            raw += resp.read1(65536)
            msgs = _read_messages(raw)
            if msgs and msgs[-1][0] == MSG_END:
                break
        aus = [m for m in msgs if m[0] == MSG_AU]
        assert len(aus) == 30 and aus[0][1] & 1
        assert msgs[-1][0] == MSG_END
        status = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{web.port}/status", timeout=5).read())
        assert status["pictures"] == 30 and status["streaming"] is False
        # The page is only on this PC.
        assert web.url.startswith("http://127.0.0.1:")
    finally:
        server.stop()
        web.stop()


def test_preview_off_decodes_nothing_but_still_feeds_obs(qapp, stream):
    vport = _free_port()
    server = VideoServer(vport, use_gpu=False)
    server.preview_enabled = False
    got = []
    server.sink = lambda cid, aus: got.extend(aus)
    kinds = []
    server.decoder_kind.connect(kinds.append)
    server.start()
    try:
        deadline = time.time() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", vport), timeout=1) as s:
                    s.sendall(stream)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        deadline = time.time() + 5
        while len(got) < 30 and time.time() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.02)
        assert len(got) == 30
        assert server.latest.take() is None and not kinds    # no decoder was even created
    finally:
        server.stop()


# --- late OBS viewers: re-encoded stream -------------------------------------------------
def test_viewer_joining_after_the_key_frame_is_gone_gets_the_fixed_stream(stream):
    from app.web_source import MSG_RESET
    hub = StreamHub()
    sp = AccessUnitSplitter()
    aus = sp.feed(stream) + sp.finish()
    hub.feed(1, aus[:1])              # the phone's only key frame...
    hub._gop, hub._gop_bytes = [], 0  # ...already dropped from the short replay
    hub.feed(1, aus[1:3])
    c = hub.subscribe()
    assert hub.fix_wanted() and c.mode == "fix"
    assert c.q.get_nowait()[0] == MSG_RESET
    hub.feed(1, aus[3:4])             # phone pictures are not sent to a fix viewer
    hub.publish_fixed(b"\x00\x00\x00\x01\x41delta", False)   # no key yet: still waiting
    assert c.q.empty()
    hub.publish_fixed(b"\x00\x00\x00\x01\x65key", True)
    hub.publish_fixed(b"\x00\x00\x00\x01\x41delta", False)
    assert c.q.qsize() == 2
    hub.end(1)                        # next mirroring starts with a key frame: pass again
    assert c.mode == "pass" and not hub.fix_wanted()


def test_repairer_makes_regular_key_frames_with_headers(stream):
    from app.repair import Repairer, has_sps
    out = []
    rep = Repairer(lambda: True, lambda au, key: out.append((au, key)), fps=30)
    dec = H264Decoder(use_gpu=True, keep_on_gpu=True)
    sp = AccessUnitSplitter()
    for au, _ in sp.feed(stream) + sp.finish():
        for f in dec.decode_au(au):
            rep.push(f)
    rep.close()
    assert rep.kind in ("h264_nvenc", "h264_mf", "libx264")
    assert len(out) >= 28 and out[0][1] and has_sps(out[0][0])
    # The re-encoded pictures decode on their own (what the OBS page does).
    check = H264Decoder(use_gpu=False)
    frames = [f for au, _ in out for f in check.decode_au(au)]
    assert len(frames) >= 28 and (frames[0].width, frames[0].height) == (320, 640)


def test_repairer_idles_when_nobody_needs_it(stream):
    from app.repair import Repairer
    rep = Repairer(lambda: False, lambda au, key: None)
    dec = H264Decoder(use_gpu=False)
    sp = AccessUnitSplitter()
    for au, _ in (sp.feed(stream) + sp.finish())[:5]:
        for f in dec.decode_au(au):
            rep.push(f)
    assert not rep.active


def test_phone_view_cached_drawing_matches_full_drawing():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QPainter
    from app.phone_view import PhoneView
    img = QImage(300, 650, QImage.Format_RGB32)
    img.fill(QColor("#3366cc"))
    view = PhoneView(0.6, "natural", "PC")
    view.show_frame(img)
    fast = view.grab().toImage()
    # Same picture through the old full-drawing path.
    from app import phone_skin as skin
    layout = skin.PhoneLayout.create(view.scale)
    slow = QImage(fast.size(), QImage.Format_ARGB32_Premultiplied)
    slow.setDevicePixelRatio(fast.devicePixelRatio())
    slow.fill(0)
    p = QPainter(slow)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    t = view._transform(layout)
    p.setTransform(t)
    skin.paint_shadow(p, layout, view.scale)
    skin.paint_buttons(p, layout, view.scale, "natural")
    skin.paint_body(p, layout, view.scale, "natural")
    p.save()
    p.setClipPath(skin.screen_path(layout, view.scale))
    view._paint_video(p, layout, t)
    p.restore()
    p.setTransform(t)
    skin.paint_island(p, layout, view.scale, active=True)
    skin.paint_glass_glare(p, layout, view.scale)
    p.end()
    a = fast.convertToFormat(QImage.Format_ARGB32)
    b = slow.convertToFormat(QImage.Format_ARGB32)
    pa = np.frombuffer(a.constBits(), np.uint8)[: a.sizeInBytes()].astype(int)
    pb = np.frombuffer(b.constBits(), np.uint8)[: b.sizeInBytes()].astype(int)
    assert np.abs(pa - pb).mean() < 1.5       # only anti-aliasing at the screen corners differs


def test_every_non_python_file_in_app_is_packed_into_the_exe():
    """PyInstaller only takes .py files: the OBS page was missing from 1.4.0-obs.1 ("page missing")."""
    root = Path(__file__).resolve().parent.parent
    script = (root / "setup" / "build_exe.ps1").read_text(encoding="utf-8")
    extra = [p.name for p in (root / "app").iterdir()
             if p.is_file() and p.suffix not in (".py", ".pyc")]
    assert extra, "expected app/obs_page.html"
    for name in extra:
        assert f"app\{name}" in script, f"{name} is not added with --add-data in setup/build_exe.ps1"
