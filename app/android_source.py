# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Android phones over USB, using the official scrcpy server (Genymobile, Apache-2.0).

How it works (scrcpy v5.0.1 protocol, checked against the server jar):
  adb push scrcpy-server /data/local/tmp/scrcpy-server.jar
  adb forward tcp:<port> localabstract:scrcpy_<scid as %08x>
  adb shell CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / \
      com.genymobile.scrcpy.Server 5.0.1 scid=<hex> tunnel_forward=true raw_stream=true \
      audio=false control=false video_codec=h264 ...
With raw_stream=true the video socket carries plain H.264 (no dummy byte, no headers),
the same thing UxPlay sends for an iPhone. So the bytes are simply relayed into the app's
own video port (VideoServer) and everything after that (preview, OBS link, repair for
late viewers) is shared with the iPhone path.

The phone needs Developer options + USB debugging switched on once, and the "Allow USB
debugging?" prompt accepted. Statuses for the waiting screen:
  android_no_adb · android_waiting · android_unauthorized · connecting · running
"""
from __future__ import annotations

import logging
import random
import socket
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .android_wifi import connect_known
from .config import AppConfig
from .i18n import T
from .paths import RESOURCE_DIR
from .win_job import KillOnCloseJob

log = logging.getLogger(__name__)

SCRCPY_VERSION = "5.0.1"        # must equal the server jar's version exactly
DEVICE_JAR = "/data/local/tmp/scrcpy-server.jar"
VENDOR = RESOURCE_DIR / "vendor" / "scrcpy"
POLL_S = 1.5
WIFI_RETRY_S = 5.0          # how often to look for Wi‑Fi-paired phones while waiting
CONNECT_TIMEOUT_S = 8.0
LOG_LIMIT = 2000
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW: no console flashes from adb


def find_adb(cfg: AppConfig) -> Path | None:
    if cfg.adb_path:
        p = Path(cfg.adb_path)
        return p if p.is_file() else None
    p = VENDOR / "adb.exe"
    return p if p.is_file() else None


def parse_devices(text: str) -> list[tuple[str, str]]:
    """`adb devices` output → [(serial, state)], state = device | unauthorized | offline …"""
    out = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and not line.startswith("List of devices") and not line.startswith("*"):
            out.append((parts[0], parts[1]))
    return out


def server_args(cfg: AppConfig, scid: int) -> list[str]:
    """Options for scrcpy-server (names exactly as the v5.0.1 server parses them)."""
    return [
        f"scid={scid:08x}",
        "log_level=info",
        "tunnel_forward=true",
        "raw_stream=true",          # plain H.264: no dummy byte, no device/codec/frame headers
        "audio=false",              # PC sound for Android: not in this round
        "control=false",
        "video_codec=h264",
        "max_size=1920",
        f"max_fps={int(cfg.fps)}",
        "video_bit_rate=8000000",
        "cleanup=true",
    ]


class AndroidSource(QObject):
    """Same interface as UxPlayReceiver, so SourceManager can switch between them."""

    log_line = Signal(str)
    status_changed = Signal(str)
    client_event = Signal(str)

    def __init__(self, cfg: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._lines: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._job = KillOnCloseJob()
        self._status = ""

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def update_config(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="android-source")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill_server()
        if self._thread is not None:
            self._thread.join(5)
        self._thread = None
        self._set_status("stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    # --- internals ---------------------------------------------------------------------
    def _emit_log(self, line: str) -> None:
        self._lines = (self._lines + [line])[-LOG_LIMIT:]
        self.log_line.emit(line)

    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.status_changed.emit(status)

    def _adb(self, adb: Path, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
        return subprocess.run([str(adb), *args], capture_output=True, text=True, timeout=timeout,
                              creationflags=NO_WINDOW, errors="replace")

    def _loop(self) -> None:
        announced_missing = False
        next_wifi = 0.0
        while not self._stop.is_set():
            adb = find_adb(self._cfg)
            if adb is None:
                if not announced_missing:
                    self._emit_log(T("adb not found. Run setup\\get_scrcpy.ps1"))
                    announced_missing = True
                self._set_status("android_no_adb")
                self._stop.wait(3)
                continue
            try:
                devices = parse_devices(self._adb(adb, "devices").stdout)
            except (OSError, subprocess.SubprocessError) as exc:
                self._emit_log(f"adb: {exc}")
                self._set_status("android_no_adb")
                self._stop.wait(3)
                continue
            ready = [s for s, st in devices if st == "device"]
            if not ready:
                waiting_auth = any(st == "unauthorized" for _s, st in devices)
                self._set_status("android_unauthorized" if waiting_auth else "android_waiting")
                # Phones paired over Wi‑Fi before: connect them when they show up on the
                # network (Wireless debugging switched on). Not every poll: mDNS is slower.
                if time.monotonic() >= next_wifi:
                    next_wifi = time.monotonic() + WIFI_RETRY_S
                    for addr in connect_known(adb):
                        self._emit_log(T("Android phone over Wi‑Fi: {addr}").format(addr=addr))
                self._stop.wait(POLL_S)
                continue
            serial = ready[0]
            try:
                self._session(adb, serial)
            except Exception as exc:  # noqa: BLE001 - keep polling whatever happens
                log.exception("android session failed")
                self._emit_log(T("Android connection failed: {err}").format(err=exc))
            finally:
                self._kill_server()
            self._stop.wait(1.0)

    def _session(self, adb: Path, serial: str) -> None:
        server = VENDOR / "scrcpy-server" if not self._cfg.scrcpy_server else Path(self._cfg.scrcpy_server)
        self._set_status("connecting")
        self.client_event.emit("connecting")
        self._emit_log(T("Android phone found: {serial}").format(serial=serial))
        res = self._adb(adb, "-s", serial, "push", str(server), DEVICE_JAR, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"adb push: {res.stderr.strip() or res.stdout.strip()}")
        scid = random.randrange(1, 0x7FFFFFFF)
        port = _free_port()
        name = f"scrcpy_{scid:08x}"
        res = self._adb(adb, "-s", serial, "forward", f"tcp:{port}", f"localabstract:{name}")
        if res.returncode != 0:
            raise RuntimeError(f"adb forward: {res.stderr.strip()}")
        try:
            cmd = [str(adb), "-s", serial, "shell", f"CLASSPATH={DEVICE_JAR}", "app_process", "/",
                   "com.genymobile.scrcpy.Server", SCRCPY_VERSION, *server_args(self._cfg, scid)]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          creationflags=NO_WINDOW)
            self._job.assign(self._proc.pid)
            threading.Thread(target=self._pump_server_log, args=(self._proc,), daemon=True).start()
            phone = self._connect(port)
            if phone is None:
                raise RuntimeError(T("the phone did not start sending video"))
            self._set_status("running")
            self._relay(phone)
        finally:
            self._adb(adb, "-s", serial, "forward", "--remove", f"tcp:{port}")

    def _pump_server_log(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._emit_log(f"[scrcpy] {line}")

    def _connect(self, port: int) -> tuple[socket.socket, bytes] | None:
        """In forward mode adb accepts at once even before the server listens, then
        closes: retry until the first video bytes arrive."""
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        while time.monotonic() < deadline and not self._stop.is_set():
            if self._proc is not None and self._proc.poll() is not None:
                return None                      # the server exited (wrong version, …)
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
            except OSError:
                time.sleep(0.2)
                continue
            s.settimeout(1.0)
            try:
                first = s.recv(65536)
            except socket.timeout:
                first = None                     # connected, screen not changing yet
            except OSError:
                first = b""
            if first == b"":
                s.close()
                time.sleep(0.2)
                continue
            return s, first or b""
        return None

    def _relay(self, phone: tuple[socket.socket, bytes]) -> None:
        """Phone → the app's VideoServer port, exactly like UxPlay's tcpclientsink."""
        sock, first = phone
        with sock, socket.create_connection(("127.0.0.1", self._cfg.video_port), timeout=5) as app:
            app.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if first:
                app.sendall(first)
            sock.settimeout(0.5)
            while not self._stop.is_set():
                try:
                    data = sock.recv(256 * 1024)
                except socket.timeout:
                    if self._proc is not None and self._proc.poll() is not None:
                        break
                    continue
                except OSError:
                    break
                if not data:
                    break
                app.sendall(data)
        self._emit_log(T("Android phone disconnected"))
        self.client_event.emit("closed")

    def _kill_server(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
