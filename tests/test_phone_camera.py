# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Direct phone camera: fake phone_cam.html + a copy of the server relay on 127.0.0.1."""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app import phone_camera as pcam
from app.config import AppConfig, validate

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "setup"))
import fake_phone_cam as fake  # noqa: E402


def wait_for(cond, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class World:
    """Relay + phone on their own loop, in a thread (the app's link has its own)."""

    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.loop = asyncio.new_event_loop()
        self.relay_stop = None
        self.phone_stop = None
        self.phone = None
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            self.relay_stop = asyncio.Event()
            up = asyncio.Event()
            self.loop.create_task(fake.run_relay(self.port, up, self.relay_stop))
            self.loop.run_until_complete(up.wait())
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert ready.wait(10)

    def start_phone(self, room, w=1080, h=1920):
        self.phone = fake.FakePhone(self.url, room, w, h, 30)

        def go():
            self.phone_stop = asyncio.Event()
            self.loop.create_task(self.phone.run(self.phone_stop))
        self.loop.call_soon_threadsafe(go)

    def stop_phone(self):
        self.loop.call_soon_threadsafe(self.phone_stop.set)

    def close(self):
        async def end():
            if self.phone_stop:
                self.phone_stop.set()
                await asyncio.sleep(0.5)
            self.relay_stop.set()
            await asyncio.sleep(0.5)
            for t in asyncio.all_tasks():
                if t is not asyncio.current_task():
                    t.cancel()
            await asyncio.sleep(0.1)
            self.loop.stop()
        asyncio.run_coroutine_threadsafe(end(), self.loop)
        self.thread.join(5)


@pytest.fixture
def world():
    w = World()
    yield w
    w.close()


def test_phone_url_asks_for_the_camera_size():
    q = parse_qs(urlparse(pcam.phone_url("om_abc123", "portrait")).query)
    assert (q["room"], q["w"], q["h"], q["fps"]) == (["om_abc123"], ["720"], ["1280"], ["24"])
    assert q["lite"] == ["1"]                            # no preview, screen kept on
    assert max(pcam.QUALITY["1080p"]) <= 1280             # 1080 lines heat an iPhone in minutes
    assert pcam.phone_url("om_abc123", "720p").startswith("https://obs-hub.web.app/phone_cam.html?")


def test_room_setting():
    room = pcam.new_room()
    assert validate(AppConfig(camera_room=room)).camera_room == room
    assert validate(AppConfig(camera_room="x\"><script>")).camera_room == ""
    assert validate(AppConfig(camera_source="usb")).camera_source == "mirror"
    assert AppConfig().camera_source == "mirror"         # mirroring stays the default


def test_browser_ice_candidate():
    c = pcam.ice_from_browser({"candidate": "candidate:1 1 udp 2122260223 192.168.1.20 50000 typ host",
                               "sdpMid": "0", "sdpMLineIndex": 0})
    assert (c.ip, c.port, c.type, c.sdpMid) == ("192.168.1.20", 50000, "host", "0")
    assert pcam.ice_from_browser({"candidate": ""}) is None   # end of candidates


def test_phone_picture_arrives_and_ends(world):
    got, ended = [], []
    link = pcam.PhoneCamLink("om_t1", lambda f: got.append(f), world.url)
    link.on_end = lambda: ended.append(1)
    link.start()
    try:
        assert wait_for(lambda: link.state == "waiting", 10)
        world.start_phone("om_t1")                       # the phone opens the page after us
        assert wait_for(lambda: len(got) >= 10, 20), link.state
        f = got[-1].to_ndarray(format="bgr24")
        assert f.shape == (1920, 1080, 3) and link.state == "live"
        assert f[100, 540][2] > 230 and f[1800, 540][0] > 230    # red top, blue bottom
        world.stop_phone()
        assert wait_for(lambda: ended and link.state == "waiting", 10)
    finally:
        link.stop()
    assert link.state == "stopped"


def test_phone_already_waiting_when_we_join(world):
    world.start_phone("om_t2", 1280, 720)
    time.sleep(1.0)
    got = []
    link = pcam.PhoneCamLink("om_t2", lambda f: got.append(f.width), world.url)
    link.start()
    try:
        assert wait_for(lambda: len(got) >= 5, 20)
        assert got[-1] == 1280 and world.phone.calls == 1     # one call, not one per retry
    finally:
        link.stop()


def test_other_room_sees_nothing(world):
    world.start_phone("om_other")
    got = []
    link = pcam.PhoneCamLink("om_mine", lambda f: got.append(f), world.url)
    link.start()
    try:
        time.sleep(3)
        assert not got and link.state == "waiting"
    finally:
        link.stop()


def test_server_down_is_offline_not_a_crash():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    link = pcam.PhoneCamLink("om_t3", lambda f: None, f"http://127.0.0.1:{port}")
    link.start()
    try:
        assert wait_for(lambda: link.state == "offline", 15)
    finally:
        link.stop()


def test_phone_camera_reaches_the_virtual_camera(world):
    from app import virtual_camera as vc
    if not (vc.is_registered() and vc.dll_path().is_file()):
        pytest.skip("camera not built/registered")
    cam = vc.VirtualCamera("720p", 30)
    if not cam.start():
        pytest.skip(f"camera busy ({cam.error})")
    cam.fill = True
    link = pcam.PhoneCamLink("om_t4", cam.push, world.url)
    link.on_end = cam.stream_ended
    link.start()
    try:
        world.start_phone("om_t4", 1920, 1080)          # 16:9 camera into a 720p frame
        assert wait_for(lambda: link.frames > 5, 20)
        import av
        c = av.open("video=" + vc.CAMERA_NAME, format="dshow")
        try:
            for i, f in enumerate(c.decode(video=0)):
                if i >= 20:
                    img = f.to_ndarray(format="bgr24")
                    break
        finally:
            c.close()
        assert img.shape == (720, 1280, 3)
        assert img[100, 640][2] > 230 and img[620, 640][0] > 230     # fills the frame, no bars
        assert cam.converted > 0
    finally:
        link.stop()
        cam.stop()


def test_slow_camera_never_falls_behind():
    """A camera that is slower than the phone gets the newest frame, not a growing queue."""
    seen = []

    def slow_sink(f):
        time.sleep(0.05)
        seen.append(f)

    out = pcam.LatestFrame(slow_sink)
    try:
        for i in range(20):
            out.put(i)
            time.sleep(0.005)
        assert wait_for(lambda: seen and seen[-1] == 19, 2)
        assert len(seen) < 6 and out.dropped >= 14      # old frames replaced, not queued
    finally:
        out.close()


def test_decoder_does_not_hold_frames():
    import av
    from aiortc.codecs import h264
    pcam.use_low_delay_decoder()
    pcam.use_low_delay_decoder()                         # twice is harmless
    assert h264.H264Decoder().codec.flags & av.codec.context.Flags.low_delay
