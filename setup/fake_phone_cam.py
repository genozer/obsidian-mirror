# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Stand-ins for testing app/phone_camera.py without a phone or the real server.

* `relay` — the webcam part of obs-hub server.js (webcam_join / webcam_signal / peer_left),
  on 127.0.0.1.
* `phone` — what public/phone_cam.html does: join as broadcaster, call every viewer with an
  offer, trickle ICE as browser JSON, send a test picture (red top, blue bottom).

    python setup/fake_phone_cam.py relay --port 5099
    python setup/fake_phone_cam.py phone --url http://127.0.0.1:5099 --room om_x --size 1080x1920 --seconds 30
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import time

import av
import numpy as np


# --- relay (copy of server.js behaviour) -------------------------------------------------------
async def run_relay(port: int, ready: asyncio.Event | None = None, stop: asyncio.Event | None = None):
    import socketio
    from aiohttp import web
    sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
    app = web.Application()
    sio.attach(app)
    roles: dict[str, str] = {}
    rooms: dict[str, str] = {}

    @sio.on("webcam_join")
    async def join(sid, data):
        room = (data or {}).get("room")
        if not isinstance(room, str) or not room or len(room) > 80:
            return
        r = "webcam:" + room
        await sio.enter_room(sid, r)
        rooms[sid] = r
        roles[sid] = "broadcaster" if data.get("role") == "broadcaster" else "viewer"
        ids = [p[0] if isinstance(p, tuple) else p for p in sio.manager.get_participants("/", r)]
        peers = [{"id": p, "role": roles.get(p, "viewer")} for p in ids if p != sid]
        await sio.emit("webcam_peers", {"peers": peers}, to=sid)
        await sio.emit("webcam_peer_joined", {"id": sid, "role": roles[sid]}, room=r, skip_sid=sid)

    @sio.on("webcam_signal")
    async def signal(sid, data):
        if data and data.get("to") and data.get("payload"):
            await sio.emit("webcam_signal", {"from": sid, "payload": data["payload"]}, to=data["to"])

    @sio.on("webcam_leave")
    async def leave(sid):
        r = rooms.pop(sid, None)
        if r:
            await sio.emit("webcam_peer_left", {"id": sid}, room=r, skip_sid=sid)
            await sio.leave_room(sid, r)

    @sio.event
    async def disconnect(sid, *_):
        r = rooms.pop(sid, None)
        if r:
            await sio.emit("webcam_peer_left", {"id": sid}, room=r, skip_sid=sid)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    if ready is not None:
        ready.set()
    await (stop or asyncio.Event()).wait()
    await runner.cleanup()


# --- phone ------------------------------------------------------------------------------------
def test_picture(w: int, h: int) -> np.ndarray:
    img = np.zeros((h, w, 3), np.uint8)
    img[: h // 2, :, 2] = 255
    img[h // 2:, :, 0] = 255
    return img


def make_track(w: int, h: int, fps: int):
    from aiortc import VideoStreamTrack

    class Pattern(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self._img = test_picture(w, h)
            self._n = 0
            self._t0 = None

        async def recv(self):
            if self._t0 is None:
                self._t0 = time.perf_counter()
            self._n += 1
            delay = self._t0 + self._n / fps - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            img = self._img.copy()
            img[(self._n * 7) % h, :, :] = 255          # a moving line: every frame differs
            f = av.VideoFrame.from_ndarray(img, format="bgr24").reformat(format="yuv420p")
            f.pts, f.time_base = self._n * (90000 // fps), fractions.Fraction(1, 90000)
            return f

    return Pattern()


class FakePhone:
    def __init__(self, url: str, room: str, w=1080, h=1920, fps=30):
        self.url, self.room, self.w, self.h, self.fps = url, room, w, h, fps
        self.pcs = {}
        self.calls = 0

    async def run(self, stop: asyncio.Event):
        import socketio
        from aiortc import RTCPeerConnection, RTCSessionDescription
        sio = socketio.AsyncClient()

        async def call(vid):
            old = self.pcs.pop(vid, None)
            if old is not None:
                if old.connectionState == "connected":
                    self.pcs[vid] = old
                    return
                await old.close()
            pc = RTCPeerConnection()
            self.pcs[vid] = pc
            self.calls += 1
            pc.addTrack(make_track(self.w, self.h, self.fps))
            await pc.setLocalDescription(await pc.createOffer())
            # aiortc puts candidates in the SDP; also trickle them like a browser does
            await sio.emit("webcam_signal", {"to": vid, "payload": {"type": "offer", "sdp": pc.localDescription.sdp}})
            for line in pc.localDescription.sdp.splitlines():
                if line.startswith("a=candidate:"):
                    await sio.emit("webcam_signal", {"to": vid, "payload": {"type": "ice", "candidate": {
                        "candidate": line[2:], "sdpMid": "0", "sdpMLineIndex": 0}}})

        @sio.event
        async def connect():
            await sio.emit("webcam_join", {"room": self.room, "role": "broadcaster"})

        @sio.on("webcam_peers")
        async def peers(data):
            for p in (data or {}).get("peers", []):
                if p.get("role") == "viewer":
                    await call(p["id"])

        @sio.on("webcam_peer_joined")
        async def joined(data):
            if data.get("role") == "viewer":
                await call(data["id"])

        @sio.on("webcam_signal")
        async def signal(data):
            pc = self.pcs.get(data.get("from"))
            p = data.get("payload") or {}
            if pc is not None and p.get("type") == "answer" and pc.signalingState == "have-local-offer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=p["sdp"], type="answer"))

        await sio.connect(self.url, transports=["websocket"])
        await stop.wait()
        await sio.emit("webcam_leave")
        for pc in self.pcs.values():
            await pc.close()
        await sio.disconnect()


async def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["relay", "phone"])
    ap.add_argument("--port", type=int, default=5099)
    ap.add_argument("--url", default="http://127.0.0.1:5099")
    ap.add_argument("--room", default="om_test")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=0)
    a = ap.parse_args()
    stop = asyncio.Event()
    if a.seconds:
        asyncio.get_running_loop().call_later(a.seconds, stop.set)
    if a.what == "relay":
        await run_relay(a.port, stop=stop)
    else:
        w, h = (int(x) for x in a.size.split("x"))
        await FakePhone(a.url, a.room, w, h, a.fps).run(stop)


if __name__ == "__main__":
    asyncio.run(_cli())
