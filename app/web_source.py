# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""OBS Browser Source on localhost (added in the Obsidian Mirror fork).

The H.264 that UxPlay forwards (split into whole pictures by VideoServer) is passed on
untouched to a small web page
(`http://127.0.0.1:<port>/obs.html`). The page decodes it with WebCodecs, i.e. on the
graphics card inside OBS's own browser, so OBS needs no window capture and this app
does no extra work per viewer.

Stream format on `/stream`: the bytes "OBM1", then messages
    [type u8][flags u8][length u32 big-endian][payload]
    type 1 = one access unit (one picture) in Annex-B; flags bit 0 = key frame
    type 2 = the stream ended (the phone stopped mirroring)
    type 3 = reset: the next pictures start a different stream (wait for its key frame)
The iPhone sends a key frame only when mirroring starts, so a viewer that joins later gets
a re-encoded copy with regular key frames instead (StreamHub, repair.py).
"""
from __future__ import annotations

import json
import logging
import queue
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PORT = 47080
MAGIC = b"OBM1"
MSG_AU = 1
MSG_END = 2
MSG_RESET = 3                          # drop the decoder and wait for a key frame
GOP_LIMIT_BYTES = 8 * 1024 * 1024      # short replay of the phone's own pictures
CLIENT_QUEUE = 240                     # pictures waiting for one slow viewer
PAGE_PATH = Path(__file__).with_name("obs_page.html")

NAL_SLICE, NAL_IDR, NAL_SEI, NAL_SPS, NAL_PPS, NAL_AUD = 1, 5, 6, 7, 8, 9


def iter_nals(buf: bytes):
    """(start, end) of every complete NAL unit (start codes stripped) in `buf`, and the
    offset where the unfinished tail begins."""
    starts = []
    i, n = 0, len(buf)
    while True:
        j = buf.find(b"\x00\x00\x01", i)
        if j < 0:
            break
        starts.append(j + 3)
        i = j + 3
    nals = []
    for k in range(len(starts) - 1):
        end = starts[k + 1] - 3
        if end > starts[k] and buf[end - 1] == 0:   # 4-byte start code of the next NAL
            end -= 1
        nals.append((starts[k], end))
    tail = starts[-1] - 3 if starts else n
    if starts and tail > 0 and buf[tail - 1] == 0:
        tail -= 1
    return nals, (tail if starts else max(0, n - 3))


class AccessUnitSplitter:
    """Turns an Annex-B byte stream (cut anywhere by TCP) into whole pictures."""

    def __init__(self) -> None:
        self._buf = b""
        self._au: list[bytes] = []
        self._au_has_vcl = False
        self._au_key = False

    def _flush(self) -> tuple[bytes, bool] | None:
        if not self._au or not self._au_has_vcl:
            return None
        au = b"".join(b"\x00\x00\x00\x01" + nal for nal in self._au)
        key = self._au_key
        self._au, self._au_has_vcl, self._au_key = [], False, False
        return au, key

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        out: list[tuple[bytes, bool]] = []
        self._buf += data
        nals, tail = iter_nals(self._buf)
        for s, e in nals:
            nal = self._buf[s:e]
            if not nal:
                continue
            kind = nal[0] & 0x1F
            vcl = kind in (NAL_SLICE, NAL_IDR)
            # A new picture starts at AUD/SPS/PPS/SEI after a slice, or at a slice whose
            # first_mb_in_slice is 0 (first bit of the slice header is 1).
            first_slice = vcl and len(nal) > 1 and (nal[1] & 0x80)
            if self._au_has_vcl and ((kind in (NAL_AUD, NAL_SPS, NAL_PPS, NAL_SEI)) or first_slice):
                done = self._flush()
                if done:
                    out.append(done)
            if kind == NAL_AUD:
                continue                      # not needed by WebCodecs
            self._au.append(nal)
            if vcl:
                self._au_has_vcl = True
                if kind == NAL_IDR:
                    self._au_key = True
        self._buf = self._buf[tail:]
        return out

    def finish(self) -> list[tuple[bytes, bool]]:
        """End of stream: the last picture (its NAL has no following start code)."""
        out: list[tuple[bytes, bool]] = []
        if self._buf:
            out = self.feed(b"\x00\x00\x00\x01\x09\xf0")    # a fake AUD closes the last NAL
            self._buf = b""
        done = self._flush()
        return out + ([done] if done else [])


def message(kind: int, payload: bytes = b"", flags: int = 0) -> bytes:
    return struct.pack(">BBI", kind, flags, len(payload)) + payload


class _Client:
    def __init__(self, mode: str, size: int = CLIENT_QUEUE) -> None:
        self.q: queue.Queue[bytes | None] = queue.Queue(size)
        # "pass": the phone's own pictures, untouched (joined at a key frame).
        # "fix":  re-encoded pictures with regular key frames (joined late; see repair.py).
        self.mode = mode
        self.waiting = mode == "fix"     # a fix viewer starts at a re-encoded key frame


class StreamHub:
    """Fans pictures out to every open Browser Source; thread-safe.

    The iPhone sends a key frame only when mirroring starts (checked on a real phone:
    1,201 pictures in 20 s, none of them key frames). A viewer that was open at that
    moment gets the phone's pictures untouched. A viewer that comes later (OBS reloaded the
    page, a scene was switched on) gets the re-encoded "fix" stream, which VideoServer
    produces only while such a viewer exists.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[_Client] = []
        self._gop: list[bytes] = []          # phone pictures since its key frame (short-lived)
        self._gop_bytes = 0
        self._fix_gop: list[bytes] = []      # re-encoded pictures since their last key frame
        self._source: int | None = None      # TCP connection currently sending video
        self.pictures = 0
        self.fixed_pictures = 0

    # --- input (video thread) ----------------------------------------------------
    def feed(self, conn_id: int, aus: list[tuple[bytes, bool]]) -> None:
        """Whole pictures from VideoServer (already split by AccessUnitSplitter)."""
        with self._lock:
            if self._source != conn_id:
                if self._source is not None and conn_id < self._source:
                    return                   # an older connection still trickling: ignore
                self._source = conn_id
                self._gop, self._gop_bytes = [], 0
                self._fix_gop = []
            for au, key in aus:
                self._publish(au, key)

    def end(self, conn_id: int) -> None:
        with self._lock:
            if self._source != conn_id:
                return
            self._source = None
            self._gop, self._gop_bytes = [], 0
            self._fix_gop = []
            msg = message(MSG_END)
            for c in self._clients:
                # The next mirroring starts with a key frame: everyone can take it as is.
                c.mode, c.waiting = "pass", False
                self._put(c, msg)

    def _publish(self, au: bytes, key: bool) -> None:
        msg = message(MSG_AU, au, 1 if key else 0)
        self.pictures += 1
        if key:
            self._gop, self._gop_bytes = [], 0
            for c in self._clients:
                if c.mode == "fix":          # a real key frame: back to the phone's pictures
                    c.mode, c.waiting = "pass", False
                    self._put(c, message(MSG_RESET))
        if self._gop or key:
            if self._gop_bytes + len(msg) <= GOP_LIMIT_BYTES:
                self._gop.append(msg)
                self._gop_bytes += len(msg)
            else:
                self._gop, self._gop_bytes = [], 0   # later viewers get the fix stream
        for c in self._clients:
            if c.mode == "pass" and not self._put(c, msg):
                self._to_fix(c)              # too slow (e.g. OBS hid it): continue repaired

    def publish_fixed(self, au: bytes, key: bool) -> None:
        """A re-encoded picture (from repair.py)."""
        msg = message(MSG_AU, au, 1 if key else 0)
        with self._lock:
            self.fixed_pictures += 1
            if key:
                self._fix_gop = []
            if self._fix_gop or key:
                self._fix_gop.append(msg)
            for c in self._clients:
                if c.mode != "fix" or (c.waiting and not key):
                    continue
                c.waiting = not self._put(c, msg)   # queue overflow: wait for the next key

    def _to_fix(self, c: _Client) -> None:
        c.mode, c.waiting = "fix", True
        self._put(c, message(MSG_RESET))
        if self._fix_gop:                    # a recent re-encoded key frame: start there
            c.waiting = not all(self._put(c, m) for m in self._fix_gop)

    @staticmethod
    def _put(c: _Client, msg: bytes) -> bool:
        try:
            c.q.put_nowait(msg)
            return True
        except queue.Full:
            with c.q.mutex:
                c.q.queue.clear()
            return False

    def fix_wanted(self) -> bool:
        """True while some viewer needs the re-encoded stream."""
        with self._lock:
            return any(c.mode == "fix" for c in self._clients)

    # --- viewers (HTTP threads) -------------------------------------------------------
    def subscribe(self) -> _Client:
        with self._lock:
            if self._source is None or self._gop:
                # Not mirroring yet (the next stream starts with a key frame), or the
                # phone's key frame is still in the short replay: take the pictures as is.
                c = _Client("pass", len(self._gop) + CLIENT_QUEUE)
                for msg in self._gop:
                    c.q.put_nowait(msg)
            else:
                c = _Client("fix", len(self._fix_gop) + CLIENT_QUEUE)
                c.q.put_nowait(message(MSG_RESET))
                for msg in self._fix_gop:
                    c.q.put_nowait(msg)
                    c.waiting = False
            self._clients.append(c)
        return c

    def unsubscribe(self, c: _Client) -> None:
        with self._lock:
            if c in self._clients:
                self._clients.remove(c)

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            with c.q.mutex:
                c.q.queue.clear()
            c.q.put_nowait(None)

    def status(self) -> dict:
        with self._lock:
            return {"streaming": self._source is not None, "viewers": len(self._clients),
                    "repaired_viewers": sum(c.mode == "fix" for c in self._clients),
                    "pictures": self.pictures, "repaired_pictures": self.fixed_pictures,
                    "replay_bytes": self._gop_bytes}


class _Handler(BaseHTTPRequestHandler):
    hub: StreamHub
    server_version = "ObsidianMirror"

    def log_message(self, fmt, *args) -> None:  # quiet: OBS polls often
        log.debug("http: " + fmt, *args)

    def _plain(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path in ("/", "/obs", "/obs.html"):
            try:
                body = PAGE_PATH.read_bytes()
            except OSError:
                body = b"page missing"
            self._plain(200, body, "text/html; charset=utf-8")
        elif path == "/status":
            self._plain(200, json.dumps(self.hub.status()).encode(), "application/json")
        elif path == "/stream":
            self._stream()
        else:
            self._plain(404, b"not found", "text/plain")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        client = self.hub.subscribe()
        try:
            self.wfile.write(MAGIC)
            self.wfile.flush()
            while True:
                try:
                    msg = client.q.get(timeout=5)
                except queue.Empty:
                    msg = message(0)          # keep-alive, so a dead viewer is noticed
                if msg is None:
                    break
                self.wfile.write(msg)
                self.wfile.flush()
        except (ConnectionError, OSError):
            pass
        finally:
            self.hub.unsubscribe(client)


class WebSource:
    """Runs the localhost HTTP server in a background thread."""

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.hub = StreamHub()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        # ".html": TikTok LIVE Studio only takes a link with a ".com"-like part (2-6 letters
        # after a dot) and refuses 127.0.0.1/obs. "/obs" still works for links already in OBS.
        return f"http://127.0.0.1:{self.port}/obs.html"

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        handler = type("Handler", (_Handler,), {"hub": self.hub})
        try:
            # 127.0.0.1 only: OBS runs on this PC; nothing is opened to the network.
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        except OSError as exc:
            log.error("OBS link: port %s unavailable: %s", self.port, exc)
            self._server = None
            return False
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True,
                                        name="obs-web-source")
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is None:
            return
        self.hub.close_all()
        self._server.shutdown()
        self._server.server_close()
        self._server = None
