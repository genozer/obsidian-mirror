# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Android path without a phone: setup/fake_adb.py plays adb + scrcpy-server v5.0.1."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from app.android_source import SCRCPY_VERSION, AndroidSource, parse_devices, server_args
from app.config import AppConfig
from app.video_stream import VideoServer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "setup"))
import fake_adb  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def adb_cmd(tmp_path):
    """A .cmd that runs the fake adb with this Python (like adb.exe would be run)."""
    cmd = tmp_path / "adb.cmd"
    cmd.write_text(f'@"{sys.executable}" "{ROOT / "setup" / "fake_adb.py"}" %*\r\n', encoding="ascii")
    fake_adb.STATE_DIR.mkdir(exist_ok=True)
    for f in ("forwards.json", "calls.log"):
        (fake_adb.STATE_DIR / f).unlink(missing_ok=True)
    yield cmd
    fake_adb.STATE.unlink(missing_ok=True)


def set_phone(**state) -> None:
    fake_adb.STATE.write_text(json.dumps(state))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(cond, seconds=15.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_parse_devices():
    out = "List of devices attached\nR58N123\tdevice\nemulator-5554\tunauthorized\n\n"
    assert parse_devices(out) == [("R58N123", "device"), ("emulator-5554", "unauthorized")]
    assert parse_devices("* daemon started successfully\nList of devices attached\n\n") == []


def test_server_args_match_the_v5_server():
    args = dict(a.split("=", 1) for a in server_args(AppConfig(fps=60), 0x1A2B))
    assert args["scid"] == "00001a2b"
    for k, v in fake_adb.REQUIRED.items():
        assert args[k] == v
    assert args["max_fps"] == "60"
    assert SCRCPY_VERSION == fake_adb.VERSION
    jar = ROOT / "vendor" / "scrcpy" / "scrcpy-server"
    if jar.is_file():               # the real server jar says the same version
        import zipfile
        dex = zipfile.ZipFile(jar).read("classes.dex")
        assert SCRCPY_VERSION.encode() in dex and b"raw_stream" in dex and b"tunnel_forward" in dex


def test_android_phone_streams_into_the_app(qapp, adb_cmd):
    set_phone(phone="device", seconds=6, size="360x780")
    vport = free_port()
    server = VideoServer(vport, use_gpu=False)
    server.start()
    jar = adb_cmd.parent / "scrcpy-server"
    jar.write_bytes(b"jar")
    cfg = AppConfig(source="android", adb_path=str(adb_cmd), scrcpy_server=str(jar), video_port=vport)
    src = AndroidSource(cfg)
    statuses: list[str] = []
    started: list[bool] = []
    src.status_changed.connect(statuses.append)
    server.stream_started.connect(lambda: started.append(True))
    try:
        src.start()
        assert wait_for(lambda: started, 25), f"no video; statuses={statuses}\n" + "\n".join(src.lines)
        assert wait_for(lambda: server.latest.pending, 10)
        img = server.take_image()
        assert img is not None and (img.width(), img.height()) == (360, 780)
        assert "connecting" in statuses and "running" in statuses
        calls = (fake_adb.STATE_DIR / "calls.log").read_text()
        assert "push" in calls and "forward tcp:" in calls and "com.genymobile.scrcpy.Server 5.0.1" in calls
        # The phone stops sending (unplugged): back to waiting, forward removed.
        assert wait_for(lambda: statuses[-1] == "android_waiting" or "Android phone disconnected"
                        in "\n".join(src.lines), 20)
        assert wait_for(lambda: "forward --remove" in (fake_adb.STATE_DIR / "calls.log").read_text(), 10)
    finally:
        src.stop()
        server.stop()


def test_unauthorized_and_missing_phone_statuses(qapp, adb_cmd):
    cfg = AppConfig(source="android", adb_path=str(adb_cmd))
    src = AndroidSource(cfg)
    statuses: list[str] = []
    src.status_changed.connect(statuses.append)
    try:
        set_phone(phone="unauthorized")
        src.start()
        assert wait_for(lambda: "android_unauthorized" in statuses, 15)
        set_phone(phone="none")
        assert wait_for(lambda: statuses[-1] == "android_waiting", 15)
    finally:
        src.stop()


def test_missing_adb_is_reported(qapp, tmp_path):
    src = AndroidSource(AppConfig(source="android", adb_path=str(tmp_path / "nope.exe")))
    statuses: list[str] = []
    src.status_changed.connect(statuses.append)
    try:
        src.start()
        assert wait_for(lambda: "android_no_adb" in statuses, 5)
    finally:
        src.stop()


# --- Wi‑Fi pairing with a QR code (Android 11+) -------------------------------------
def test_qr_payload_and_mdns_parsing():
    from app.android_wifi import new_credentials, parse_mdns, qr_payload
    name, pw = new_credentials()
    assert name.startswith("obsidian-") and len(pw) == 12
    assert qr_payload(name, pw) == f"WIFI:T:ADB;S:{name};P:{pw};;"
    out = ("List of discovered mdns services\n"
           "obsidian-AbC\t_adb-tls-pairing._tcp\t192.168.1.20:37099\n"
           "adb-R58N-xyz\t_adb-tls-connect._tcp.\t192.168.1.20:41235\n")
    assert parse_mdns(out) == [("obsidian-AbC", "_adb-tls-pairing._tcp", "192.168.1.20:37099"),
                               ("adb-R58N-xyz", "_adb-tls-connect._tcp", "192.168.1.20:41235")]


def test_qr_pixmap_is_a_real_qr(qapp):
    import segno
    from app.wifi_dialog import qr_pixmap
    from PySide6.QtGui import QGuiApplication  # noqa: F401 - pixmaps need a GUI app
    if QCoreApplication.instance().__class__.__name__ == "QCoreApplication":
        pytest.skip("needs QApplication")
    pm = qr_pixmap("WIFI:T:ADB;S:obsidian-x;P:secret;;", 260)
    assert pm.width() == 260
    assert segno.make("WIFI:T:ADB;S:obsidian-x;P:secret;;").version >= 2


def test_phone_scans_the_qr_pairs_and_connects(qapp, adb_cmd):
    from app.android_wifi import WifiPairing
    set_phone(phone="none")
    pairing = WifiPairing(adb_cmd)
    steps: list[str] = []
    pairing.step.connect(lambda s, d: steps.append(s))
    pairing.start()
    try:
        assert wait_for(lambda: "waiting" in steps, 15)
        # The phone scans the code: it now knows the name and the password.
        set_phone(phone="none", qr={"name": pairing.name, "password": pairing.password})
        assert wait_for(lambda: "done" in steps or "failed" in steps, 30), steps
        assert steps[-1] == "done" and "pairing" in steps and "connecting" in steps
        calls = (fake_adb.STATE_DIR / "calls.log").read_text()
        assert f"pair {fake_adb.PAIR_ADDR} {pairing.password}" in calls
    finally:
        pairing.cancel()


def test_wrong_code_is_not_paired(qapp, adb_cmd):
    from app.android_wifi import WifiPairing
    pairing = WifiPairing(adb_cmd)
    steps: list[tuple[str, str]] = []
    pairing.step.connect(lambda s, d: steps.append((s, d)))
    set_phone(phone="none", qr={"name": pairing.name, "password": "not-the-password"})
    pairing.start()
    try:
        assert wait_for(lambda: steps and steps[-1][0] == "failed", 30), steps
        assert "Wrong password" in steps[-1][1]
    finally:
        pairing.cancel()


def test_paired_phone_reconnects_by_itself_and_streams(qapp, adb_cmd):
    """Next day: Wireless debugging on, no cable — the app finds it and streams."""
    set_phone(phone="none", paired=True, seconds=5, size="320x700")
    vport = free_port()
    server = VideoServer(vport, use_gpu=False)
    server.start()
    jar = adb_cmd.parent / "scrcpy-server"
    jar.write_bytes(b"jar")
    src = AndroidSource(AppConfig(source="android", adb_path=str(adb_cmd), scrcpy_server=str(jar),
                                  video_port=vport))
    started: list[bool] = []
    server.stream_started.connect(lambda: started.append(True))
    try:
        src.start()
        assert wait_for(lambda: started, 30), "\n".join(src.lines)
        calls = (fake_adb.STATE_DIR / "calls.log").read_text()
        assert f"connect {fake_adb.WIFI_ADDR}" in calls
        assert f"-s {fake_adb.WIFI_ADDR} shell" in calls
        assert any("Wi‑Fi" in line for line in src.lines)
    finally:
        src.stop()
        server.stop()
