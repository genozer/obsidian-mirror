# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Re-encoded stream for OBS viewers that join after mirroring started.

An iPhone sends one key frame when mirroring starts and never again (measured: 1,201
pictures in 20 s, all P-frames). A Browser Source opened later cannot start decoding the
phone's pictures, so while such a viewer exists the decoded frames are encoded again with
a key frame every 2 seconds. The graphics card encoder is used when there is one
(NVIDIA NVENC, else Windows Media Foundation, which uses the card of any vendor);
libx264 is the last resort. Nothing runs when no viewer needs it.
"""
from __future__ import annotations

import logging
import time
from fractions import Fraction
from typing import Callable

import av

log = logging.getLogger(__name__)

IDLE_STOP_S = 5.0          # close the encoder this long after the last viewer needing it
KEY_EVERY_S = 2.0
ENCODERS = (
    ("h264_nvenc", {"preset": "p1", "tune": "ull", "zerolatency": "1", "delay": "0", "forced-idr": "1"}),
    ("h264_mf", {"rate_control": "cbr", "scenario": "display_remote_desktop"}),
    ("libx264", {"preset": "ultrafast", "tune": "zerolatency", "sc_threshold": "0"}),
)


def bitrate_for(width: int, height: int, fps: int) -> int:
    """Generous bitrate so the copy looks like the original (about 0.1 bit per pixel)."""
    return int(min(20_000_000, max(3_000_000, width * height * fps * 0.1)))


class Repairer:
    """Encodes decoded frames while `wanted()` says a viewer needs them."""

    def __init__(self, wanted: Callable[[], bool], publish: Callable[[bytes, bool], None],
                 fps: int = 30) -> None:
        self._wanted = wanted
        self._publish = publish
        self.fps = fps
        self._enc = None
        self._size = (0, 0)
        self._pts = 0
        self._last_key = 0.0
        self._last_need = 0.0
        self.kind = ""             # encoder in use, for the log / status
        self.on_start: Callable[[str], None] | None = None

    @property
    def active(self) -> bool:
        return self._enc is not None

    def _open(self, width: int, height: int) -> None:
        for name, opts in ENCODERS:
            try:
                enc = av.CodecContext.create(name, "w")
                enc.width, enc.height, enc.pix_fmt = width, height, "nv12"
                enc.time_base = Fraction(1, self.fps)
                enc.framerate = Fraction(self.fps, 1)
                enc.gop_size = int(self.fps * KEY_EVERY_S)
                enc.max_b_frames = 0
                enc.bit_rate = bitrate_for(width, height, self.fps)
                enc.options = dict(opts)
                enc.open()
            except Exception as exc:  # noqa: BLE001 - try the next encoder
                log.info("encoder %s unavailable: %s", name, exc)
                continue
            self._enc, self._size, self._pts, self.kind = enc, (width, height), 0, name
            self._last_key = 0.0
            log.info("repair stream: %s %dx%d", name, width, height)
            if self.on_start:
                self.on_start(name)
            return
        raise RuntimeError("no H.264 encoder available")

    def close(self) -> None:
        enc, self._enc = self._enc, None
        if enc is not None:
            try:
                for _ in enc.encode(None):
                    pass
            except Exception:  # noqa: BLE001 - closing anyway
                pass

    def push(self, frame: av.VideoFrame) -> None:
        """Called by VideoServer for every decoded frame (in order)."""
        now = time.monotonic()
        if self._wanted():
            self._last_need = now
        elif self._enc is None or now - self._last_need > IDLE_STOP_S:
            self.close()
            return
        if self._enc is None or self._size != (frame.width, frame.height):
            self.close()               # first use, or the phone rotated
            self._open(frame.width, frame.height)
        sw = frame.reformat(format="nv12")       # downloads from the graphics card if needed
        sw.pts = self._pts
        self._pts += 1
        if now - self._last_key >= KEY_EVERY_S:
            sw.pict_type = av.video.frame.PictureType.I
            self._last_key = now
        for pkt in self._enc.encode(sw):
            data, key = bytes(pkt), bool(pkt.is_keyframe)
            if key and not has_sps(data) and self._enc.extradata:
                # Some encoders keep SPS/PPS only in extradata; the page needs them in-band.
                data = bytes(self._enc.extradata) + data
            self._publish(data, key)


def has_sps(au: bytes) -> bool:
    i = au.find(b"\x00\x00\x01")
    while i >= 0:
        if i + 3 < len(au) and au[i + 3] & 0x1F == 7:
            return True
        i = au.find(b"\x00\x00\x01", i + 3)
    return False
