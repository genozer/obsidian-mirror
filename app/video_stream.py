# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub: graphics-card (D3D11VA) decoding, frames
# converted at the window's size instead of full size, preview can be switched off,
# and the raw H.264 is also handed to the OBS Browser Source (web_source.py).
"""Local TCP server: receives H.264 (Annex-B) from UxPlay and decodes frames."""
from __future__ import annotations

import logging
import socket
import threading
from typing import Callable

import av
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .i18n import T
from .web_source import AccessUnitSplitter

log = logging.getLogger(__name__)

RECV_CHUNK = 256 * 1024
ACCEPT_TIMEOUT_S = 0.5
SCALE_THREADS = 4

# (width, height, cover) the picture will be drawn at, in device pixels. 0 = full size.
TargetBox = tuple[int, int, bool]


class LatestFrame:
    """Keeps only the newest frame, so the window never falls behind the phone."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._image: QImage | None = None
        self._pending = False

    def put(self, image: QImage) -> bool:
        """Stores a frame. True if the UI must be told (the previous one was taken)."""
        with self._lock:
            self._image = image
            notify = not self._pending
            self._pending = True
            return notify

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._pending

    def take(self) -> QImage | None:
        with self._lock:
            self._pending = False
            return self._image


def scaled_size(width: int, height: int, box: TargetBox) -> tuple[int, int]:
    """Size to convert a width×height frame to for drawing in `box` (never upscales)."""
    bw, bh, cover = box
    if bw <= 0 or bh <= 0 or width <= 0 or height <= 0:
        return width, height
    kx, ky = bw / width, bh / height
    k = min(1.0, max(kx, ky) if cover else min(kx, ky))
    w = max(2, int(round(width * k / 2)) * 2)
    h = max(2, int(round(height * k / 2)) * 2)
    return min(w, width), min(h, height)


def frame_to_qimage(frame: av.VideoFrame, box: TargetBox = (0, 0, False)) -> QImage:
    """Converts (and shrinks to `box`) in one libswscale pass, straight into a QImage."""
    w, h = scaled_size(frame.width, frame.height, box)
    rgb = frame.reformat(width=w, height=h, format="bgra", interpolation="BILINEAR",
                         threads=SCALE_THREADS)
    plane = rgb.planes[0]
    # The plane may be padded (width not aligned, e.g. 886): pass its real line size.
    return QImage(bytes(plane), w, h, plane.line_size, QImage.Format_RGB32).copy()


class H264Decoder:
    """libavcodec wrapper. Uses the graphics card (D3D11VA) when it can, else the CPU."""

    def __init__(self, use_gpu: bool = True, keep_on_gpu: bool = False) -> None:
        """keep_on_gpu: frames stay in video memory and are copied back only when they
        are drawn or re-encoded (0.55 ms instead of ~3 ms of CPU per frame). Never hold
        more than a couple of such frames: the decoder's surface pool is small."""
        self.kind = "cpu"
        self._ctx = None
        if use_gpu:
            try:
                from av.codec.hwaccel import HWAccel
                self._ctx = av.CodecContext.create(
                    "h264", "r", hwaccel=HWAccel(device_type="d3d11va", allow_software_fallback=True,
                                                 is_hw_owned=keep_on_gpu))
                self.kind = "gpu"
            except Exception as exc:  # noqa: BLE001 - no D3D11 device: fall back to the CPU
                log.warning("GPU decoding unavailable, using the CPU: %s", exc)
                self._ctx = None
        if self._ctx is None:
            self._ctx = av.CodecContext.create("h264", "r")
        try:
            self._ctx.thread_type = "SLICE"   # no frame-threading delay
        except (AttributeError, ValueError):
            pass

    def decode(self, data: bytes) -> list[av.VideoFrame]:
        frames: list[av.VideoFrame] = []
        for packet in self._ctx.parse(data):
            try:
                frames.extend(self._ctx.decode(packet))
            except av.error.InvalidDataError:
                continue   # wait for the next key frame
        return frames

    def decode_au(self, au: bytes) -> list[av.VideoFrame]:
        """One whole picture (from AccessUnitSplitter). Skips libav's parser, so a frame
        comes out at once instead of waiting for the start of the next picture."""
        try:
            return list(self._ctx.decode(av.Packet(au)))
        except av.error.InvalidDataError:
            return []

    def feed(self, data: bytes) -> list[QImage]:
        """Old interface (tests): decoded frames at full size."""
        return [frame_to_qimage(f) for f in self.decode(data)]


class VideoServer(QThread):
    frame_ready = Signal()            # take the frame with latest.take()
    stream_started = Signal()
    stream_ended = Signal()
    server_error = Signal(str)
    decoder_kind = Signal(str)        # "gpu" | "cpu"

    def __init__(self, port: int, parent=None, use_gpu: bool = True) -> None:
        super().__init__(parent)
        self._port = port
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active_streams = 0          # connections that are already sending video
        self._workers: list[threading.Thread] = []
        self._conn_ids = 0
        self.latest = LatestFrame()
        self.use_gpu = use_gpu
        self.preview_enabled = True       # False: no decoding at all (OBS link only)
        self.target_box: TargetBox = (0, 0, False)
        # whole pictures [(annex-b bytes, is_key)] → OBS link
        self.sink: Callable[[int, list[tuple[bytes, bool]]], None] | None = None
        self.sink_end: Callable[[int], None] | None = None
        self.repair = None                # repair.Repairer: re-encodes for late OBS viewers
        self.camera = None                # virtual_camera.VirtualCamera (webcam for other apps)
        self._last_frame: av.VideoFrame | None = None

    def take_image(self) -> QImage | None:
        """For the GUI thread: the newest frame as a QImage at the window's size."""
        item = self.latest.take()
        if isinstance(item, av.VideoFrame):
            return frame_to_qimage(item, self.target_box)
        return item

    def full_image(self) -> QImage | None:
        """The newest frame at full resolution (for screenshots)."""
        frame = self._last_frame
        return frame_to_qimage(frame) if frame is not None else None

    def stop(self) -> None:
        self._stop.set()
        self.wait(3000)

    def run(self) -> None:
        try:
            server = socket.create_server(("127.0.0.1", self._port))
        except OSError as exc:
            self.server_error.emit(T("Port {port} is busy or unavailable: {err}").format(port=self._port, err=exc))
            return
        server.settimeout(ACCEPT_TIMEOUT_S)
        with server:
            while not self._stop.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    self.server_error.emit(T("Socket error: {err}").format(err=exc))
                    break
                # UxPlay keeps a connection open from start-up, and on reconnect the iPhone
                # may open a new one before closing the old: one thread per connection.
                worker = threading.Thread(target=self._serve_safe, args=(conn,), daemon=True)
                self._workers = [w for w in self._workers if w.is_alive()] + [worker]
                worker.start()
        for worker in self._workers:
            worker.join(2)

    def _serve_safe(self, conn: socket.socket) -> None:
        with conn:
            try:
                self._serve(conn)
            except Exception as exc:  # noqa: BLE001 - the server must survive a broken stream
                log.exception("Video stream error")
                self.server_error.emit(T("Video stream error: {err}").format(err=exc))

    def _set_streaming(self, delta: int) -> None:
        with self._lock:
            before = self._active_streams
            self._active_streams = max(0, before + delta)
            after = self._active_streams
        if before == 0 and after > 0:
            self.stream_started.emit()
        elif before > 0 and after == 0:
            self._last_frame = None
            self.stream_ended.emit()

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(ACCEPT_TIMEOUT_S)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._lock:
            self._conn_ids += 1
            conn_id = self._conn_ids
        splitter = AccessUnitSplitter()
        state = _StreamState()
        started = False
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(RECV_CHUNK)
                except socket.timeout:
                    continue
                except OSError as exc:
                    log.info("Video stream interrupted: %s", exc)
                    break
                if not data:
                    break
                if not started:
                    started = True
                    self._set_streaming(+1)
                self._handle(conn_id, splitter.feed(data), state)
            self._handle(conn_id, splitter.finish(), state)
        finally:
            if self.repair is not None and state.decoder is not None:
                self.repair.close()
            self.latest.take()            # release video-memory frames of this stream
            camera = self.camera
            if camera is not None:
                camera.stream_ended()
            end = self.sink_end
            if end is not None:
                end(conn_id)
            if started:
                self._set_streaming(-1)

    def _handle(self, conn_id: int, aus: list[tuple[bytes, bool]], st: "_StreamState") -> None:
        if not aus:
            return
        sink = self.sink
        if sink is not None:
            sink(conn_id, aus)
        repair = self.repair
        # The phone sends one key frame per session, so the decoder must see every picture
        # from the start: it keeps running while the preview or the OBS link may need it.
        # On the graphics card with frames left in video memory this costs ~0.5 ms/frame.
        camera = self.camera
        if not self.preview_enabled and repair is None and camera is None:
            return
        if st.decoder is None:
            st.decoder = H264Decoder(self.use_gpu, keep_on_gpu=True)
            self.decoder_kind.emit(st.decoder.kind)
        frames: list[av.VideoFrame] = []
        for au, _key in aus:
            for frame in st.decoder.decode_au(au):
                if repair is not None:
                    try:
                        repair.push(frame)          # re-encode for late OBS viewers (if any)
                    except Exception as exc:  # noqa: BLE001 - never break the preview
                        if not st.repair_failed:
                            st.repair_failed = True
                            log.exception("repair stream failed")
                            self.server_error.emit(T("Video stream error: {err}").format(err=exc))
                frames.append(frame)
        if frames and camera is not None:
            camera.push(frames[-1])
        if not frames or not self.preview_enabled:
            return
        frame = frames[-1]
        self._last_frame = frame
        # The window has not drawn the previous frame yet: keep this one unconverted
        # (take_image converts it if it is still the newest when the window asks).
        item = frame if self.latest.pending else frame_to_qimage(frame, self.target_box)
        if self.latest.put(item):
            self.frame_ready.emit()


class _StreamState:
    """Per-connection decoder."""

    def __init__(self) -> None:
        self.decoder: H264Decoder | None = None
        self.repair_failed = False
