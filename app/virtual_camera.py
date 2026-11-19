# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
""""Obsidian Mirror Camera": the phone picture as a webcam for TikTok LIVE Studio, Discord, Zoom…

The camera itself is a DirectShow filter (native/softcam, MIT, renamed) registered with
Windows once (native/register_camera.ps1, later the installer). Apps that open it read
frames from shared memory; this module writes them there through the DLL's sender API.

A thread of its own sends at the chosen frame rate: when a new phone picture has come in it
is scaled into the camera frame (letterboxed, black bars), otherwise the last frame is sent
again. Without a phone it shows a plain dark card — never setup instructions, because the
camera may already be live in front of viewers.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .paths import RESOURCE_DIR

log = logging.getLogger(__name__)

CAMERA_NAME = "Obsidian Mirror Camera"
CLSID = "{CCBD2AC3-77A1-4925-B6DF-78E0C090295F}"
DLL_DIR = RESOURCE_DIR / "vendor" / "camera"
SIZES = {"720p": (1280, 720), "1080p": (1920, 1080), "portrait": (1080, 1920)}
CAMERA_FPS = 30                                 # webcam rate; 60 doubles the CPU for little gain
IDLE_FPS = 5                                    # no phone / nobody watching: re-sent slowly
WATCH_GRACE_S = 2.0                             # an app read a frame this recently = watching
BG = (24, 24, 27)                               # bars and the card: near black (BGR)


def dll_path() -> Path:
    return DLL_DIR / ("obsidian_camera64.dll" if sys.maxsize > 2**32 else "obsidian_camera32.dll")


def is_registered() -> bool:
    """True when Windows knows the camera (native/register_camera.ps1 has run)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{CLSID}\InprocServer32"):
            return True
    except OSError:
        return False


def fit_box(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    """Where the phone picture goes inside the camera frame: x, y, w, h (even sizes)."""
    k = min(dst_w / src_w, dst_h / src_h)
    w = min(dst_w, max(2, round(src_w * k / 2) * 2))
    h = min(dst_h, max(2, round(src_h * k / 2) * 2))
    return (dst_w - w) // 2, (dst_h - h) // 2, w, h


def fill_size(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int]:
    """Scaled size that covers the whole camera frame (the rest is cut off), even sizes."""
    k = max(dst_w / src_w, dst_h / src_h)
    return max(dst_w, round(src_w * k / 2) * 2), max(dst_h, round(src_h * k / 2) * 2)


def crop_box(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    """The centre part of the source with the camera's shape: x, y, w, h (even numbers)."""
    k = min(src_w / dst_w, src_h / dst_h)
    w = min(src_w, max(2, int(dst_w * k) // 2 * 2))
    h = min(src_h, max(2, int(dst_h * k) // 2 * 2))
    return (src_w - w) // 4 * 2, (src_h - h) // 4 * 2, w, h


def crop_yuv420p(frame, x: int, y: int, w: int, h: int):
    """Cut a yuv420p frame before scaling: scaling all of a 1920×1080 picture to 3414×1920 and
    throwing most of it away cost ~3× the CPU (measured with the real iPhone)."""
    import av
    planes = []
    for i, (px, py, pw, ph) in enumerate(((x, y, w, h), (x // 2, y // 2, w // 2, h // 2),
                                         (x // 2, y // 2, w // 2, h // 2))):
        p = frame.planes[i]
        rows = frame.height if i == 0 else (frame.height + 1) // 2
        a = np.frombuffer(p, np.uint8).reshape(rows, p.line_size)
        planes.append(a[py:py + ph, px:px + pw])
    packed = np.concatenate([planes[0], planes[1].reshape(h // 4, w), planes[2].reshape(h // 4, w)])
    return av.VideoFrame.from_ndarray(packed, format="yuv420p")


def place(frame, canvas: np.ndarray, fill: bool = False) -> None:
    """Scale an av.VideoFrame (CPU or video memory) into the BGR canvas, centred.
    fill: cover the frame and cut the edges (the phone camera), else fit with bars (a phone screen)."""
    dst_h, dst_w = canvas.shape[:2]
    if fill and frame.format.name == "yuv420p" and (frame.width, frame.height) != (dst_w, dst_h):
        x, y, w, h = crop_box(frame.width, frame.height, dst_w, dst_h)
        if h % 4 == 0 and (w, h) != (frame.width, frame.height):
            frame = crop_yuv420p(frame, x, y, w, h)
    if fill:
        w, h = fill_size(frame.width, frame.height, dst_w, dst_h)
        img = frame.reformat(width=w, height=h, format="bgr24", interpolation="BILINEAR", threads=1).to_ndarray()
        x, y = (w - dst_w) // 2, (h - dst_h) // 2
        canvas[:] = img[y:y + dst_h, x:x + dst_w]
        return
    x, y, w, h = fit_box(frame.width, frame.height, dst_w, dst_h)
    # threads=1: the auto thread pool costs more CPU than it saves at these sizes (measured).
    img = frame.reformat(width=w, height=h, format="bgr24", interpolation="BILINEAR", threads=1).to_ndarray()
    if (x, y, w, h) != (0, 0, dst_w, dst_h):
        canvas[:] = BG
    canvas[y:y + h, x:x + w] = img


def waiting_card(width: int, height: int, text: str) -> np.ndarray:
    """Dark frame with one quiet line of text (drawn with Qt on a QImage: any thread)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    img = QImage(width, height, QImage.Format_RGB888)
    img.fill(QColor(BG[2], BG[1], BG[0]))
    p = QPainter(img)
    p.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Segoe UI")
    font.setPixelSize(max(14, min(width, height) // 28))
    p.setFont(font)
    p.setPen(QColor("#71717a"))
    p.drawText(img.rect(), Qt.AlignCenter, text)
    p.end()
    rgb = np.frombuffer(img.constBits(), np.uint8).reshape(height, img.bytesPerLine())[:, :width * 3]
    return np.ascontiguousarray(rgb.reshape(height, width, 3)[:, :, ::-1])


class _Dll:
    def __init__(self, path: Path) -> None:
        self.lib = ctypes.CDLL(str(path))
        self.lib.scCreateCamera.restype = ctypes.c_void_p
        self.lib.scCreateCamera.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_float)
        self.lib.scDeleteCamera.argtypes = (ctypes.c_void_p,)
        self.lib.scSendFrame.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self.lib.scIsConnected.restype = ctypes.c_bool
        self.lib.scIsConnected.argtypes = (ctypes.c_void_p,)
        self.lib.scIdleSeconds.restype = ctypes.c_float      # our addition (native/softcam)
        self.lib.scIdleSeconds.argtypes = (ctypes.c_void_p,)


class VirtualCamera:
    """One camera for the whole PC. start() → push(frame) from the video thread → stop().

    The picture is converted in the video thread (right after decoding): converting a
    video-memory frame from another thread was 4–6× slower (8.8 vs 1.6 ms at 720p), because
    both threads then fight over the graphics card. The sending thread only hands finished
    frames to the DLL. Three buffers: one being sent, one ready, one being written.
    """

    def __init__(self, size: str = "720p", fps: int = 30, waiting_text: str = "Waiting for the phone…",
                 dll: Path | None = None) -> None:
        self.width, self.height = SIZES.get(size, SIZES["720p"])
        self.fps = fps
        self.waiting_text = waiting_text
        self.fill = False                     # True for the phone camera: no bars, cut the edges
        self._dll_path = dll or dll_path()
        self._dll: _Dll | None = None
        self._cam = None
        self._lock = threading.Lock()
        self._bufs: list[np.ndarray] = []
        self._ready = -1                      # index of the newest finished phone frame
        self._sending = -1                    # index the sending thread is using
        self._fresh = False                   # _ready not sent yet
        self._live = False                    # a phone is mirroring
        self._last_convert = 0.0
        self._watch_checked = -10.0
        self._watch_cached = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.converted = 0
        self.error = ""

    # --- control (GUI thread) ------------------------------------------------------------
    def start(self) -> bool:
        if self._thread is not None:
            return True
        try:
            self._dll = _Dll(self._dll_path)
        except OSError as exc:
            self.error = f"camera DLL: {exc}"
            return False
        cam = self._dll.lib.scCreateCamera(self.width, self.height, float(self.fps))
        if not cam:
            self.error = "the camera is in use by another program"
            return False
        self._cam = cam
        self._card = waiting_card(self.width, self.height, self.waiting_text)
        self._bufs = [np.full((self.height, self.width, 3), BG, np.uint8) for _ in range(3)]
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="virtual-camera", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        if self._cam and self._dll:
            self._dll.lib.scDeleteCamera(self._cam)
        self._cam = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    @property
    def watched(self) -> bool:
        """An app is reading the camera right now (took a frame in the last 2 seconds)."""
        if not (self._cam and self._dll):
            return False
        idle = self._dll.lib.scIdleSeconds(self._cam)
        return 0.0 <= idle < WATCH_GRACE_S

    # --- from the video thread -------------------------------------------------------------
    def push(self, frame) -> None:
        if not self._bufs:
            return
        now = time.perf_counter()
        # The phone may send 60 fps to a 30 fps camera: skip what would never be shown.
        if self._live and now - self._last_convert < 0.85 / self.fps:
            return
        # Nobody has the camera open: converting costs ~4–6 ms of CPU per frame for nothing.
        # Check once a second; the first frame an app takes may be up to 1 s old.
        if self._live and not self._watching(now):
            return
        with self._lock:
            free = next(i for i in range(3) if i not in (self._ready, self._sending))
        try:
            place(frame, self._bufs[free], self.fill)
        except Exception as exc:              # noqa: BLE001 - one bad frame must not stop the video
            if not self.error:
                log.exception("virtual camera frame")
            self.error = str(exc)
            return
        self._last_convert = now
        self.converted += 1
        with self._lock:
            self._ready, self._fresh, self._live = free, True, True

    def _watching(self, now: float) -> bool:
        if now - self._watch_checked >= 1.0:
            self._watch_checked = now
            self._watch_cached = self.watched
        return self._watch_cached

    def push_live(self) -> None:
        """Turned on while a phone is already mirroring: no card, wait for its next picture."""
        with self._lock:
            self._live = True

    def stream_ended(self) -> None:
        with self._lock:
            self._live = False
            self._ready = -1

    # --- the sending thread --------------------------------------------------------------------
    def _run(self) -> None:
        last = None
        while not self._stop.is_set():
            with self._lock:
                live = self._live
                if self._ready >= 0 and (self._fresh or live):
                    self._sending, self._fresh = self._ready, False
                    image = self._bufs[self._sending]
                else:
                    self._sending = -1
                    image = self._card if not live else last
            if image is None:                 # turned on mid-stream: nothing converted yet
                image = self._card
            # With a frame rate set, scSendFrame waits for the right moment by itself;
            # the same frame is sent again when the phone has nothing new (static screen).
            self._dll.lib.scSendFrame(self._cam, image.ctypes.data)
            last = image
            self.sent += 1
            if not live or not self._watch_cached:
                self._stop.wait(1 / IDLE_FPS)
