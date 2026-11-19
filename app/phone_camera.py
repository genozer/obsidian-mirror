# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Direct phone camera: the obs-hub "Phone Webcam" page sends the phone's camera straight to us.

Screen mirroring copies the whole screen, so the iPhone Camera app's buttons end up in the
picture. Here the phone opens `phone_cam.html` (no app to install) and sends only the camera
over WebRTC. We join its room as a *viewer*, exactly like `webcam_overlay.html` in OBS:

    phone  --webcam_join(broadcaster)-->  obs-hub Socket.IO  <--webcam_join(viewer)--  this app
    phone  --offer / ice------------------------------------------------------------>  answer
    phone  ======== video (peer to peer, inside the home Wi‑Fi) =======================>  sink

The server only passes the few signalling messages; the video never goes through it.
Everything here runs on one asyncio loop in its own thread; `sink(frame)` is called there.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from urllib.parse import urlencode

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

SIGNAL_URL = "https://obsidian-hub.duckdns.org:5000"
PAGE_URL = "https://obs-hub.web.app/phone_cam.html"
# No STUN on our side: on this PC it makes every answer wait 5 s (adapters that cannot reach it),
# and phone and PC are on the same Wi‑Fi, so our host addresses are what the phone needs.
REJOIN_S = 8.0            # nothing coming in and no call for this long: join again
CONNECT_RETRY_S = 5.0
# camera mode → what the phone page sends (it crops to fill; the camera scales it up to its size).
# At most 720 lines: at 1080×1920 the phone's canvas redraw + H.264 encode heats an iPhone within
# 5 minutes (tried 2026-11-20, no preview, screen kept on). 720×1280 is ~2.25× less work.
QUALITY = {
    "720p": (1280, 720),
    "1080p": (1280, 720),
    "portrait": (720, 1280),
}
FPS = 24                  # 30 → 24: ~20 % less canvas + encode work on the phone (heat, 2026-11-20)
BITRATE_KBPS = 4000       # plenty for 720 lines on the home Wi-Fi; less radio work on the phone


def new_room() -> str:
    """Random room id (no account data in it). Same shape as webcam_connect.html's."""
    return "om_" + secrets.token_hex(8)


def phone_url(room: str, mode: str, page: str = PAGE_URL) -> str:
    w, h = QUALITY.get(mode, QUALITY["720p"])
    # lite=1: no preview on the phone, canvas redrawn only on new camera frames, screen kept on by a
    # tiny video (see public/phone_cam.html); the camera crops it to fill (VirtualCamera.fill).
    return page + "?" + urlencode({"room": room, "w": w, "h": h, "fps": FPS, "br": BITRATE_KBPS, "lite": 1})


def ice_from_browser(c: dict):
    """Browser RTCIceCandidate JSON → aiortc candidate (None for end-of-candidates)."""
    from aiortc.sdp import candidate_from_sdp
    text = (c or {}).get("candidate") or ""
    if not text:
        return None
    cand = candidate_from_sdp(text.split(":", 1)[1] if text.startswith("candidate:") else text)
    cand.sdpMid = c.get("sdpMid")
    cand.sdpMLineIndex = c.get("sdpMLineIndex")
    return cand


def use_bitrate_floor(floor_bps: int = BITRATE_KBPS * 1000) -> None:
    """aiortc's bandwidth estimate (REMB, the only one it sends) stays far too low: the real
    iPhone was held at ~0.4 Mbps for 1080×1920, so the picture was soft. Phone and PC share
    one Wi‑Fi, so never ask for less than the page's own maximum; the phone still backs off
    by itself when packets get lost."""
    import aiortc.rtcrtpreceiver as rx
    if getattr(rx.RemoteBitrateEstimator, "_obsidian_floor", None) == floor_bps:
        return
    base = getattr(rx.RemoteBitrateEstimator, "_obsidian_base", rx.RemoteBitrateEstimator)

    class Floored(base):
        _obsidian_floor = floor_bps
        _obsidian_base = base

        def add(self, *args, **kwargs):
            out = super().add(*args, **kwargs)
            if out is None:
                return None
            bitrate, ssrcs = out
            return max(int(bitrate), floor_bps), ssrcs

    rx.RemoteBitrateEstimator = Floored


def use_low_delay_decoder() -> None:
    """Phone video has no B-frames: tell the H.264 decoder not to hold frames back waiting for
    reordering (it may otherwise keep a few frames = ~100 ms before the first one comes out)."""
    import av
    from aiortc.codecs import h264
    if getattr(h264.H264Decoder, "_obsidian_low_delay", False):
        return
    base_init = h264.H264Decoder.__init__

    def __init__(self, *args, **kwargs):
        base_init(self, *args, **kwargs)
        self.codec.flags |= av.codec.context.Flags.low_delay

    h264.H264Decoder.__init__ = __init__
    h264.H264Decoder._obsidian_low_delay = True


class LatestFrame:
    """Hand frames to the camera on its own thread, keeping only the newest one. Converting
    a frame for the camera takes ~5–15 ms: done on the network loop it held back incoming
    packets, and frames that arrived meanwhile waited in a queue that never shrinks (delay
    only grows during a live). Here a frame that is not taken in time is replaced, not queued."""

    def __init__(self, sink) -> None:
        self.sink = sink
        self.dropped = 0
        self.busy_ms = 0.0                    # time spent in sink since the last stats line
        self._frame = None
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="phone-camera-sink", daemon=True)
        self._thread.start()

    def put(self, frame) -> None:
        with self._cv:
            if self._frame is not None:
                self.dropped += 1
            self._frame = frame
            self._cv.notify()

    def close(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._frame is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                frame, self._frame = self._frame, None
            t = time.perf_counter()
            try:
                self.sink(frame)
            except Exception:                 # noqa: BLE001 - one bad frame must not stop us
                log.exception("phone camera sink")
            self.busy_ms += (time.perf_counter() - t) * 1000


class PhoneCamLink(QObject):
    """Receive the phone camera. States: connecting · offline · waiting · live · stopped."""

    state_changed = Signal(str)

    def __init__(self, room: str, sink, signal_url: str = SIGNAL_URL, parent=None) -> None:
        super().__init__(parent)
        self.room = room
        self.sink = sink                      # called with each av.VideoFrame (loop thread)
        self.on_end = None                    # called when the phone stops sending
        self.signal_url = signal_url
        self.state = "stopped"
        self.frames = 0
        self.size = (0, 0)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._pcs: dict = {}                  # phone socket id → RTCPeerConnection
        self._live_from = ""
        self._last_offer = 0.0
        self._inbox: asyncio.Queue | None = None

    # --- Qt side -------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="phone-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._set_state("stopped")

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            log.info("phone camera: %s", state)
            self.state_changed.emit(state)

    # --- loop thread ---------------------------------------------------------------------------
    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:                     # noqa: BLE001 - never take the app down
            log.exception("phone camera loop")

    async def _main(self) -> None:
        import socketio
        use_bitrate_floor()
        use_low_delay_decoder()
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        sio = socketio.AsyncClient(reconnection=True, reconnection_delay=2, reconnection_delay_max=10)
        self._sio = sio

        @sio.event
        async def connect():
            self._set_state("waiting")
            await self._join()

        @sio.event
        async def disconnect(*_):
            if not self._stop.is_set():
                self._set_state("offline")

        @sio.on("webcam_peer_left")
        async def peer_left(data):
            await self._close_pc((data or {}).get("id"))

        @sio.on("webcam_signal")
        async def signal(data):
            # handlers run side by side: ICE must not overtake the offer it belongs to
            self._inbox.put_nowait(data or {})

        self._inbox = asyncio.Queue()
        self._set_state("connecting")
        rejoin = asyncio.create_task(self._rejoin_loop())
        worker = asyncio.create_task(self._signal_worker())
        while not self._stop.is_set():
            try:
                await sio.connect(self.signal_url, transports=["websocket"], wait_timeout=10)
                break
            except Exception as exc:          # noqa: BLE001 - offline, DNS, TLS…
                log.info("phone camera: signalling server unreachable (%s)", exc)
                self._set_state("offline")
                try:
                    await asyncio.wait_for(self._stop.wait(), CONNECT_RETRY_S)
                except asyncio.TimeoutError:
                    pass
        await self._stop.wait()
        rejoin.cancel()
        worker.cancel()
        for pid in list(self._pcs):
            await self._close_pc(pid)
        try:
            if sio.connected:
                await sio.emit("webcam_leave")
            await sio.disconnect()
        except Exception:                     # noqa: BLE001
            pass

    async def _join(self) -> None:
        await self._sio.emit("webcam_join", {"room": self.room, "role": "viewer"})

    async def _rejoin_loop(self) -> None:
        """The phone calls us when it sees us join. If a call got lost, join again."""
        while True:
            await asyncio.sleep(REJOIN_S)
            quiet = time.monotonic() - self._last_offer > REJOIN_S
            if self._sio.connected and not self._pcs and quiet:
                await self._join()

    async def _signal_worker(self) -> None:
        while True:
            data = await self._inbox.get()
            try:
                await self._on_signal(data)
            except Exception:                 # noqa: BLE001 - a bad message must not stop us
                log.exception("phone camera signal")

    async def _on_signal(self, data: dict) -> None:
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
        src, payload = data.get("from"), data.get("payload") or {}
        if not src:
            return
        if payload.get("type") == "offer":
            self._last_offer = time.monotonic()
            await self._close_pc(src)
            pc = RTCPeerConnection(RTCConfiguration([]))
            self._pcs[src] = pc

            @pc.on("track")
            def on_track(track):
                asyncio.ensure_future(self._pump(src, track))

            @pc.on("connectionstatechange")
            async def on_state():
                if pc.connectionState in ("failed", "closed") and self._pcs.get(src) is pc:
                    await self._close_pc(src)

            await pc.setRemoteDescription(RTCSessionDescription(sdp=payload["sdp"], type="offer"))
            await pc.setLocalDescription(await pc.createAnswer())   # aiortc: candidates included
            await self._sio.emit("webcam_signal", {"to": src, "payload": {
                "type": pc.localDescription.type, "sdp": pc.localDescription.sdp}})
        elif payload.get("type") == "ice" and src in self._pcs:
            cand = ice_from_browser(payload.get("candidate"))
            if cand is not None:
                await self._pcs[src].addIceCandidate(cand)

    async def _pump(self, src: str, track) -> None:
        """Read every frame (an unread track queues forever). Audio is dropped for now.
        Frames already waiting behind the one we got are skipped: show the newest, never
        fall behind (an asyncio.Queue in aiortc, unbounded)."""
        from aiortc.mediastreams import MediaStreamError
        video = track.kind == "video"
        out = LatestFrame(self.sink) if video else None
        skipped, backlog, last_log = 0, 0, time.monotonic()
        try:
            while True:
                frame = await track.recv()
                if not video:
                    continue
                q = getattr(track, "_queue", None)
                if q is not None:
                    backlog = max(backlog, q.qsize())
                    while q.qsize() > 0:
                        newer = q.get_nowait()
                        if newer is None:     # end marker: keep it for the next recv()
                            q.put_nowait(None)
                            break
                        frame, skipped = newer, skipped + 1
                self._live_from = src
                self.frames += 1
                self.size = (frame.width, frame.height)
                if self.state != "live":
                    self._set_state("live")
                out.put(frame)
                now = time.monotonic()
                if now - last_log >= 30:
                    log.info("phone camera: %dx%d · skipped %d late + %d not taken · backlog max %d"
                             " · camera %.1f ms/frame", frame.width, frame.height, skipped,
                             out.dropped, backlog, out.busy_ms / max(1, self.frames))
                    skipped, backlog, last_log = 0, 0, now
        except (MediaStreamError, asyncio.CancelledError):
            pass
        finally:
            if out is not None:
                out.close()
        if video and self._live_from == src:
            self._ended()

    def _ended(self) -> None:
        self._live_from = ""
        if self.on_end is not None:
            self.on_end()
        if self._stop is not None and not self._stop.is_set():
            self._set_state("waiting" if self._sio.connected else "offline")

    async def _close_pc(self, src) -> None:
        pc = self._pcs.pop(src, None)
        if pc is not None:
            await pc.close()
            if self._live_from == src:
                self._ended()

