# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Android over Wi‑Fi: pair once with a QR code, then connect automatically.

Android 11+ "Wireless debugging" → "Pair device with QR code" scans a code of the form
    WIFI:T:ADB;S:<service name>;P:<password>;;
(the same one Android Studio shows). The phone then announces an mDNS service
_adb-tls-pairing._tcp named <service name>; we find it with `adb mdns services` and run
`adb pair <ip:port> <password>`. After that the phone announces _adb-tls-connect._tcp and
`adb connect <ip:port>` (adb also auto-connects these by default) makes it show up in
`adb devices`, so AndroidSource streams from it exactly like a USB phone.
"""
from __future__ import annotations

import logging
import secrets
import string
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

PAIRING = "_adb-tls-pairing._tcp"
CONNECT = "_adb-tls-connect._tcp"
NO_WINDOW = 0x08000000
PAIR_TIMEOUT_S = 180          # how long the QR code stays valid
CONNECT_TIMEOUT_S = 30
ALPHABET = string.ascii_letters + string.digits


def qr_payload(name: str, password: str) -> str:
    return f"WIFI:T:ADB;S:{name};P:{password};;"


def new_credentials() -> tuple[str, str]:
    name = "obsidian-" + "".join(secrets.choice(ALPHABET) for _ in range(8))
    password = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return name, password


def parse_mdns(text: str) -> list[tuple[str, str, str]]:
    """`adb mdns services` → [(instance name, service type, "ip:port")]."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "._tcp" in parts[1] and ":" in parts[-1]:
            out.append((parts[0], parts[1].rstrip("."), parts[-1]))
    return out


def run_adb(adb: Path, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run([str(adb), *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW, errors="replace")


def connect_known(adb: Path) -> list[str]:
    """Connects every phone that announces _adb-tls-connect (only phones paired with this
    PC accept). Returns the addresses that connected. Called while waiting for a phone."""
    done = []
    try:
        services = parse_mdns(run_adb(adb, "mdns", "services", timeout=8).stdout)
    except (OSError, subprocess.SubprocessError):
        return done
    for _name, kind, addr in services:
        if kind != CONNECT:
            continue
        try:
            res = run_adb(adb, "connect", addr, timeout=8)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (res.stdout + res.stderr).lower()
        if "connected to" in text and "cannot" not in text and "failed" not in text:
            done.append(addr)
    return done


class WifiPairing(QObject):
    """Runs one QR pairing in the background. Steps for the dialog:
    waiting (show the code) → pairing → connecting → done | failed."""

    step = Signal(str, str)        # (step, detail)

    def __init__(self, adb: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.name, self.password = new_credentials()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def payload(self) -> str:
        return qr_payload(self.name, self.password)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="android-wifi-pair")
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def _services(self) -> list[tuple[str, str, str]]:
        try:
            return parse_mdns(run_adb(self.adb, "mdns", "services", timeout=8).stdout)
        except (OSError, subprocess.SubprocessError) as exc:
            log.info("mdns services: %s", exc)
            return []

    def _run(self) -> None:
        try:
            check = run_adb(self.adb, "mdns", "check", timeout=10)
            if "version" not in (check.stdout + check.stderr).lower():
                self.step.emit("failed", "mdns")
                return
        except (OSError, subprocess.SubprocessError) as exc:
            self.step.emit("failed", str(exc))
            return
        self.step.emit("waiting", "")
        end = time.monotonic() + PAIR_TIMEOUT_S
        addr = None
        while not self._stop.is_set() and time.monotonic() < end:
            addr = next((a for n, k, a in self._services() if k == PAIRING and n == self.name), None)
            if addr:
                break
            self._stop.wait(1.0)
        if self._stop.is_set():
            return
        if not addr:
            self.step.emit("failed", "timeout")
            return
        self.step.emit("pairing", addr)
        res = run_adb(self.adb, "pair", addr, self.password, timeout=30)
        text = res.stdout + res.stderr
        if "successfully paired" not in text.lower():
            self.step.emit("failed", text.strip()[:200])
            return
        ip = addr.rsplit(":", 1)[0]
        self.step.emit("connecting", ip)
        end = time.monotonic() + CONNECT_TIMEOUT_S
        while not self._stop.is_set() and time.monotonic() < end:
            # adb auto-connects new pairs by default; connect explicitly as well.
            devices = run_adb(self.adb, "devices", timeout=8).stdout
            if any(line.startswith(ip) or ("_adb-tls-connect" in line and "\tdevice" in line)
                   for line in devices.splitlines()):
                self.step.emit("done", ip)
                return
            for _n, k, a in self._services():
                if k == CONNECT and a.startswith(ip + ":"):
                    run_adb(self.adb, "connect", a, timeout=8)
            self._stop.wait(1.0)
        if not self._stop.is_set():
            self.step.emit("failed", "connect timeout")
