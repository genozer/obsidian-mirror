# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Feedback button: the details it attaches and the dashboard link it opens."""
from __future__ import annotations

import base64
import json
from urllib.parse import urlparse

from app import __version__
from app import feedback as fb
from app.config import AppConfig


def decode(url: str) -> dict:
    """What public/dash/support.js does with #mirror=… (base64url, no padding)."""
    frag = urlparse(url).fragment
    assert frag.startswith("mirror=")
    raw = frag[len("mirror="):]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))


def test_log_line_has_no_addresses_or_user_folder():
    line = (r"Android connection failed: 192.168.1.20:41235 aa:bb:cc:dd:ee:ff fe80::1:2:3:4%12 "
            r"2407:b1c0:dd0:7385:5708:4681:d417:8153 C:\Users\somebody\x at 02:14:35")
    out = fb.scrub(line)
    for gone in ("192.168", "aa:bb", "fe80", "2407", "somebody"):
        assert gone not in out
    assert out.startswith("Android connection failed") and out.endswith("at 02:14:35")   # times stay


def test_last_error_picks_the_newest_problem():
    lines = ["started", "Decoder: d3d11va", "Android connection failed: timeout", "Phone: iPhone", "all good"]
    assert fb.last_error(lines) == "Android connection failed: timeout"
    assert fb.last_error(["all good"]) == ""


def test_link_carries_the_details_after_the_hash():
    cfg = AppConfig(camera="portrait", camera_source="phone")
    diag = fb.build_diag(cfg, ["x" * 500 + " error"], "live 720x1280")
    url = fb.feedback_url(diag)
    assert url.startswith(fb.DASHBOARD_URL + "#mirror=")      # after '#': never sent to a server
    back = decode(url)
    assert back["version"] == __version__ and back["phone_cam"] == "live 720x1280"
    assert back["camera"] == "portrait / phone"
    assert len(back) <= fb.MAX_KEYS and all(len(v) <= fb.MAX_LEN for v in back.values())


def test_never_more_than_seven_keys():
    many = {f"k{i}": "v" for i in range(20)}
    assert len(decode(fb.feedback_url(many))) == fb.MAX_KEYS
