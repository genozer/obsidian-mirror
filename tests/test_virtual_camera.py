# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Virtual camera: real DLL, frames read back the way apps read them (DirectShow)."""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app import virtual_camera as vc
from app.config import AppConfig, validate

ROOT = Path(__file__).resolve().parent.parent
needs_camera = pytest.mark.skipif(not (vc.is_registered() and vc.dll_path().is_file()),
                                  reason="camera not built/registered (native/build_camera.ps1, register_camera.ps1)")


@pytest.fixture(autouse=True)
def camera_free(request):
    """The camera is one per PC: if the running app has it on, the live tests cannot run."""
    if request.node.get_closest_marker("skipif") is None or not vc.is_registered():
        return
    probe = vc.VirtualCamera("720p", 30)
    if not probe.start():
        pytest.skip(f"camera busy ({probe.error}) — turn it off in the running app")
    probe.stop()


def phone_frame(w=886, h=1920) -> av.VideoFrame:
    img = np.zeros((h, w, 3), np.uint8)
    img[: h // 2, :, 2] = 255          # red top
    img[h // 2:, :, 0] = 255           # blue bottom
    return av.VideoFrame.from_ndarray(img, format="bgr24").reformat(format="yuv420p")


def read_camera(n=1, feed=None) -> np.ndarray:
    c = av.open("video=" + vc.CAMERA_NAME, format="dshow")
    try:
        for i, f in enumerate(c.decode(video=0)):
            if feed:
                feed()
            if i + 1 >= n:
                return f.to_ndarray(format="bgr24")
    finally:
        c.close()


def test_fit_box_letterboxes():
    assert vc.fit_box(886, 1920, 1280, 720) == (474, 0, 332, 720)
    assert vc.fit_box(1920, 1080, 1280, 720) == (0, 0, 1280, 720)
    assert vc.fit_box(1170, 2532, 1080, 1920) == (96, 0, 888, 1920)


def test_fill_crops_instead_of_bars():
    import av as _av
    assert vc.fill_size(1920, 1440, 1080, 1920) == (2560, 1920)       # 4:3 landscape into portrait
    img = np.zeros((1440, 1920, 3), np.uint8)
    img[:, :, 1] = 200                                                   # green everywhere
    fr = _av.VideoFrame.from_ndarray(img, format="bgr24").reformat(format="yuv420p")
    canvas = np.zeros((1920, 1080, 3), np.uint8)
    vc.place(fr, canvas, fill=True)
    assert canvas[5, 5][1] > 180 and canvas[1915, 1075][1] > 180       # no bars anywhere


def test_fill_cuts_before_scaling_same_picture():
    """Landscape phone camera into the portrait camera: cut the middle first (the iPhone sends
    1920×1080), the picture must match scaling everything and cutting afterwards."""
    import av as _av
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:, :, 0] = np.linspace(0, 255, 1920)[None, :]
    img[:, :, 2] = np.linspace(0, 255, 1080)[:, None]
    fr = _av.VideoFrame.from_ndarray(img, format="bgr24").reformat(format="yuv420p")
    assert vc.crop_box(1920, 1080, 1080, 1920) == (656, 0, 606, 1080)
    fast = np.zeros((1920, 1080, 3), np.uint8)
    vc.place(fr, fast, fill=True)
    w, h = vc.fill_size(1920, 1080, 1080, 1920)
    slow = fr.reformat(width=w, height=h, format="bgr24").to_ndarray()
    slow = slow[(h - 1920) // 2:(h - 1920) // 2 + 1920, (w - 1080) // 2:(w - 1080) // 2 + 1080]
    assert np.abs(fast.astype(int) - slow.astype(int)).max() <= 8


def test_setting_values():
    assert validate(AppConfig(camera="4k")).camera == "off"
    assert AppConfig().camera == "off"            # off unless the streamer turns it on


def test_waiting_card_is_plain():
    card = vc.waiting_card(320, 180, "x")
    assert card.shape == (180, 320, 3) and tuple(card[5, 5]) == vc.BG


@needs_camera
def test_camera_shows_card_then_phone_then_card_again():
    cam = vc.VirtualCamera("720p", 30)
    assert cam.start(), cam.error
    try:
        idle = read_camera()
        assert idle.shape == (720, 1280, 3) and tuple(idle[360, 100]) == vc.BG
        fr = phone_frame()
        live = read_camera(20, feed=lambda: cam.push(fr))
        assert live[100, 640][2] > 240 and live[100, 640][0] < 15       # red top, centred
        assert live[620, 640][0] > 240 and live[620, 640][2] < 15       # blue bottom
        assert tuple(live[360, 50]) == vc.BG                            # black bar at the side
        assert cam.watched and cam.converted > 0
        cam.stream_ended()
        time.sleep(0.5)
        after = read_camera(3)
        assert tuple(after[100, 640]) == vc.BG                          # no frozen phone picture
    finally:
        cam.stop()


@needs_camera
def test_portrait_size_and_second_camera_refused():
    cam = vc.VirtualCamera("portrait", 30)
    assert cam.start(), cam.error
    try:
        other = vc.VirtualCamera("720p", 30)
        assert not other.start() and "in use" in other.error
        assert read_camera().shape == (1920, 1080, 3)
    finally:
        cam.stop()
    again = vc.VirtualCamera("720p", 30)            # free again after stop
    assert again.start()
    again.stop()


@needs_camera
def test_phone_stream_reaches_the_camera_through_the_video_server():
    """fake iPhone H.264 → VideoServer decode → camera → read back."""
    from app.video_stream import VideoServer
    sys.path.insert(0, str(ROOT / "tests"))
    from test_obsidian_fork import make_h264
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = VideoServer(port, use_gpu=False)
    server.preview_enabled = False                  # preview off: only the camera needs pictures
    cam = vc.VirtualCamera("720p", 30)
    assert cam.start()
    server.camera = cam
    server.start()
    try:
        data = make_h264()
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(data)
            end = time.time() + 10
            while cam.converted == 0 and time.time() < end:
                QApplication.processEvents()
                time.sleep(0.05)
        assert cam.converted > 0
    finally:
        server.stop()
        cam.stop()


@needs_camera
def test_no_work_while_no_app_watches():
    cam = vc.VirtualCamera("720p", 30)
    assert cam.start()
    try:
        fr = phone_frame()
        for _ in range(30):
            cam.push(fr)
            time.sleep(0.02)
        assert cam.converted <= 1 and not cam.watched     # nobody reads: (almost) nothing converted
        live = read_camera(25, feed=lambda: cam.push(fr))  # an app opens it: pictures flow
        assert cam.converted > 5 and live[100, 640][2] > 240
    finally:
        cam.stop()
