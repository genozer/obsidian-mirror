# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""A pretend `adb` + Android phone, for testing the Android path without a phone.

Point the app at it with a .cmd wrapper (config "adb_path"); see tests/test_android.py.
It answers `devices`, `push`, `forward`, and for `shell ... com.genymobile.scrcpy.Server`
it checks the command the way scrcpy-server v5.0.1 would (exact version, scid, the raw
stream options) and then streams H.264 on the forwarded port like the real server with
raw_stream=true (plain Annex-B, no headers).

State (in %TEMP%/obsidian_fake_adb/state.json, editable while the app runs):
  {"phone": "device" | "unauthorized" | "none", "seconds": 600, "size": "720x1560"}
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

STATE_DIR = Path(tempfile.gettempdir()) / "obsidian_fake_adb"
STATE = STATE_DIR / "state.json"
FORWARDS = STATE_DIR / "forwards.json"
SERIAL = "FAKE0001"
PAIR_ADDR = "127.0.0.1:37001"       # where the phone listens for pairing
WIFI_ADDR = "127.0.0.1:37002"       # where it listens for adb over Wi‑Fi
VERSION = "5.0.1"
REQUIRED = {"tunnel_forward": "true", "raw_stream": "true", "audio": "false",
            "control": "false", "video_codec": "h264"}


def state() -> dict:
    try:
        return {"phone": "device", "seconds": 600, "size": "720x1560", **json.loads(STATE.read_text())}
    except (OSError, ValueError):
        return {"phone": "device", "seconds": 600, "size": "720x1560"}


def save(**changes) -> None:
    STATE.write_text(json.dumps({**state(), **changes}))


def fake_mdns(args: list[str], st: dict) -> int:
    """The phone's Wireless debugging: after "scanning" the QR (state "qr" set by the
    test) it announces _adb-tls-pairing; once paired it announces _adb-tls-connect."""
    if args[:1] == ["check"]:
        print("mdns daemon version [fake adb discovery]")
        return 0
    print("List of discovered mdns services")
    qr = st.get("qr")
    if qr and not st.get("paired"):
        print(f"{qr['name']}\t_adb-tls-pairing._tcp\t{PAIR_ADDR}")
    if st.get("paired") and st.get("announce", True):
        print(f"adb-{SERIAL}-wifi\t_adb-tls-connect._tcp\t{WIFI_ADDR}")
    return 0


def log(msg: str) -> None:
    with open(STATE_DIR / "calls.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main(argv: list[str]) -> int:
    STATE_DIR.mkdir(exist_ok=True)
    log("adb " + " ".join(argv))
    st = state()
    if argv[:1] == ["-s"]:
        if argv[1] not in (SERIAL, WIFI_ADDR if st.get("wifi") else SERIAL):
            print(f"adb: device '{argv[1]}' not found", file=sys.stderr)
            return 1
        if argv[1] == WIFI_ADDR:
            st["phone"] = "device"
        argv = argv[2:]
    cmd = argv[0] if argv else ""
    if cmd == "devices":
        print("List of devices attached")
        if st["phone"] != "none":
            print(f"{SERIAL}\t{st['phone']}")
        if st.get("wifi"):
            print(f"{WIFI_ADDR}\tdevice")
        print()
        return 0
    if cmd == "mdns":
        return fake_mdns(argv[1:], st)
    if cmd == "pair":
        qr = st.get("qr") or {}
        if argv[1:3] == [PAIR_ADDR, qr.get("password")]:
            save(paired=True)
            print(f"Successfully paired to {PAIR_ADDR} [guid=adb-{SERIAL}-wifi]")
            return 0
        print("Failed: Wrong password or connection was dropped.")
        return 1
    if cmd == "connect":
        if st.get("paired") and argv[1] == WIFI_ADDR:
            save(wifi=True)
            print(f"connected to {WIFI_ADDR}")
            return 0
        print(f"failed to connect to '{argv[1]}': Connection refused")
        return 1
    if st["phone"] != "device":
        print("adb: device unauthorized or missing", file=sys.stderr)
        return 1
    if cmd == "push":
        if not Path(argv[1]).is_file():
            print(f"adb: cannot stat '{argv[1]}'", file=sys.stderr)
            return 1
        print(f"{argv[1]}: 1 file pushed.")
        return 0
    if cmd == "forward":
        fw = json.loads(FORWARDS.read_text()) if FORWARDS.exists() else {}
        if argv[1] == "--remove":
            fw.pop(argv[2], None)
        else:
            fw[argv[1]] = argv[2]
        FORWARDS.write_text(json.dumps(fw))
        return 0
    if cmd == "shell":
        return fake_server(argv[1:], st)
    print(f"fake adb: unknown command {argv}", file=sys.stderr)
    return 1


def fake_server(args: list[str], st: dict) -> int:
    # CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 5.0.1 k=v…
    if (len(args) < 5 or args[0] != "CLASSPATH=/data/local/tmp/scrcpy-server.jar"
            or args[1:4] != ["app_process", "/", "com.genymobile.scrcpy.Server"]):
        print(f"fake server: bad command {args}", flush=True)
        return 1
    if args[4] != VERSION:
        print(f'ERROR: The server version ({VERSION}) does not match the client ({args[4]})', flush=True)
        return 1
    opts = dict(a.split("=", 1) for a in args[5:])
    for k, v in REQUIRED.items():
        if opts.get(k) != v:
            print(f"fake server: expected {k}={v}, got {opts.get(k)}", flush=True)
            return 1
    name = f"scrcpy_{int(opts['scid'], 16):08x}"
    fw = json.loads(FORWARDS.read_text()) if FORWARDS.exists() else {}
    port = next((int(k.split(":")[1]) for k, v in fw.items() if v == f"localabstract:{name}"), None)
    if port is None:
        print(f"fake server: no adb forward to {name}", flush=True)
        return 1
    print(f"[server] INFO: Device: [Fake] Obsidian Test Phone (Android 15)", flush=True)
    stream(port, st, float(opts.get("max_fps", "30")))
    return 0


def stream(port: int, st: dict, fps: float) -> None:
    import av
    import numpy as np
    w, h = (int(x) for x in st["size"].split("x"))
    srv = socket.create_server(("127.0.0.1", port))
    srv.settimeout(10)
    conn, _ = srv.accept()
    enc = av.CodecContext.create("libx264", "w")
    enc.width, enc.height, enc.pix_fmt = w, h, "yuv420p"
    enc.time_base = Fraction(1, int(fps))
    enc.framerate = Fraction(int(fps), 1)
    enc.gop_size = int(fps * 10)                      # like Android MediaCodec in scrcpy
    enc.options = {"preset": "ultrafast", "tune": "zerolatency", "bf": "0"}
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.zeros((h, w, 3), np.uint8)
    base[..., 1] = (yy * 200 // h).astype(np.uint8)    # green-ish: easy to tell from the iPhone test
    base[..., 2] = (xx * 255 // w).astype(np.uint8)
    t0 = time.perf_counter()
    try:
        for i in range(int(st["seconds"] * fps)):
            img = base.copy()
            y = int((i * 10) % (h - 120))
            img[y:y + 120, w // 5: 4 * w // 5] = (255, 255, 255)
            frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")
            frame.pts = i
            for pkt in enc.encode(frame):
                conn.sendall(bytes(pkt))
            delay = t0 + (i + 1) / fps - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
    except OSError:
        pass                                           # the client went away
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
