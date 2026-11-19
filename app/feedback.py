# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
""""Send feedback": open the dashboard's support chat with this program's details attached.

The program has no login, the support chat does (it answers the streamer in their own
account). So the button opens https://obs-hub.web.app/dashboard#mirror=<base64url JSON>;
the dashboard keeps it in sessionStorage across a login, opens "แจ้งปัญหา" with a new case
and adds these keys to the system info it already attaches (public/dash/support.js).
After '#' nothing reaches any server until the streamer presses send.

At most 7 short keys (the server keeps 12 keys of 200 characters, the browser uses 5).
Addresses, MACs and user folders are removed from the log line.
"""
from __future__ import annotations

import base64
import json
import platform
import re

from . import __version__

DASHBOARD_URL = "https://obs-hub.web.app/dashboard"
MAX_KEYS = 7
MAX_LEN = 200
_ERROR_WORDS = re.compile(r"error|fail|exception|traceback|crash|ไม่สำเร็จ|ผิดพลาด|หลุด", re.I)
# Order matters: MAC before IPv6 (both use colons); timestamps like 02:14:35 must survive.
_SCRUB = [
    (re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I), "<mac>"),
    (re.compile(r"\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b", re.I), "<ip>"),            # full IPv6
    (re.compile(r"(?<![\w:])[0-9a-f]{0,4}(?::[0-9a-f]{0,4})*::[0-9a-f:]*(?:%\w+)?", re.I), "<ip>"),  # fe80::1
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.I), r"C:\\Users\\<user>"),
]


def scrub(text: str) -> str:
    for pattern, repl in _SCRUB:
        text = pattern.sub(repl, text)
    return text


def last_error(lines: list[str]) -> str:
    for line in reversed(lines or []):
        if _ERROR_WORDS.search(line):
            return scrub(line.strip())[-MAX_LEN:]
    return ""


def windows_name() -> str:
    release, version, *_ = platform.win32_ver() + ("", "")
    if release or version:
        return f"Windows {release} {version}".strip()
    return platform.platform()


def build_diag(cfg, log_lines: list[str], phone_state: str = "") -> dict[str, str]:
    diag = {
        "version": __version__,
        "windows": windows_name(),
        "source": getattr(cfg, "source", ""),
        "camera": f"{getattr(cfg, 'camera', '')} / {getattr(cfg, 'camera_source', '')}",
        "phone_cam": phone_state,
        "last_error": last_error(log_lines),
    }
    return {k: str(v)[:MAX_LEN] for k, v in diag.items() if v}


def feedback_url(diag: dict[str, str], base: str = DASHBOARD_URL) -> str:
    small = dict(list(diag.items())[:MAX_KEYS])
    raw = json.dumps(small, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base + "#mirror=" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
