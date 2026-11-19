# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Test without an iPhone: sends a moving test picture to the app's video port, the same
way UxPlay does (raw H.264 over local TCP). Like an iPhone, it sends one key frame at the
start and then only changes, so a late OBS viewer must be served from the replay buffer.

    python setup/fake_iphone.py [--seconds 60] [--fps 30] [--port 47011] [--size 886x1920]
"""
from __future__ import annotations

import argparse
import socket
import time
from fractions import Fraction

import av
import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--port", type=int, default=47011)
    ap.add_argument("--size", default="886x1920")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.split("x"))

    enc = av.CodecContext.create("libx264", "w")
    enc.width, enc.height, enc.pix_fmt = w, h, "yuv420p"
    enc.time_base = Fraction(1, a.fps)
    enc.framerate = Fraction(a.fps, 1)
    enc.gop_size = 100000
    enc.options = {"preset": "ultrafast", "tune": "zerolatency", "sc_threshold": "0", "bf": "0"}

    yy, xx = np.mgrid[0:h, 0:w]
    base = np.zeros((h, w, 3), np.uint8)
    base[..., 0] = (xx * 255 // w).astype(np.uint8)
    base[..., 2] = (yy * 255 // h).astype(np.uint8)

    sock = socket.create_connection(("127.0.0.1", a.port))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    total = int(a.seconds * a.fps)
    t0 = time.perf_counter()
    for i in range(total):
        img = base.copy()
        y = int((i * 12) % (h - 200))
        img[y:y + 200, w // 4: 3 * w // 4] = (255, 255, 255)          # moving white bar
        sec = i // a.fps
        img[40:40 + 60, 40:40 + 60 * (sec % 10 + 1)] = (40, 220, 90)  # grows every second
        frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")
        frame.pts = i
        for pkt in enc.encode(frame):
            sock.sendall(bytes(pkt))
        delay = t0 + (i + 1) / a.fps - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    sock.close()
    print(f"sent {total} frames")


if __name__ == "__main__":
    main()
