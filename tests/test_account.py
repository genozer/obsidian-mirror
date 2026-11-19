# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Sign-in: the whole browser round trip against a stand-in for /api/mirror/* (the real one
is modules/mirror_auth.js on the obs-hub server, tested there with test/mirror_auth.test.js)."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from app import account as acc
from app.login_dialog import LoginDialog

b64url = acc.b64url


class FakeHub:
    """Does what modules/mirror_auth.js does, plus the mirror_login.html "Allow" press."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}          # code → challenge
        self.tokens: set[str] = set()
        self.off = False
        self.down = False
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                if hub.down:
                    self.send_response(503)
                    self.end_headers()
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)) or b"{}")
                token = self.headers.get("x-mirror-token", "")
                code, out = 200, {"success": True}
                if self.path == "/api/mirror/token":
                    ch = hub.codes.pop(body.get("code", ""), None)
                    want = b64url(hashlib.sha256(body.get("verifier", "").encode()).digest())
                    if hub.off:
                        code, out = 403, {"success": False, "error": "feature_disabled"}
                    elif not ch or ch != want:
                        code, out = 400, {"success": False, "error": "bad_code"}
                    else:
                        t = b64url(secrets.token_bytes(32))
                        hub.tokens.add(t)
                        out = {"success": True, "token": t, "user": {"username": "alice", "tier": "basic"}}
                elif self.path == "/api/mirror/me":
                    if token not in hub.tokens:
                        code, out = 401, {"success": False, "error": "not_logged_in"}
                    elif hub.off:
                        code, out = 403, {"success": False, "error": "feature_disabled"}
                    else:
                        out = {"success": True, "user": {"username": "alice", "tier": "ultra"}}
                elif self.path == "/api/mirror/logout":
                    hub.tokens.discard(token)
                raw = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def browser(self, url: str, state_override: str | None = None) -> int:
        """What the browser + mirror_login.html do after the streamer presses "Allow"."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        code = b64url(secrets.token_bytes(32))
        self.codes[code] = q["challenge"]
        cb = (f"http://127.0.0.1:{q['port']}/callback?"
              + urllib.parse.urlencode({"code": code, "state": state_override or q["state"]}))
        try:
            return urllib.request.urlopen(cb, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code


@pytest.fixture()
def hub():
    h = FakeHub()
    yield h
    h.server.shutdown()


def make(hub, tmp_path, now=time.time):
    return acc.Account(tmp_path / "account.dat", api=hub.url, page="https://obs-hub.invalid/mirror_login.html", now=now)


def test_pkce_matches_the_server_rule():
    verifier, challenge = acc.new_pkce()
    assert len(verifier) == len(challenge) == 43
    assert challenge == b64url(hashlib.sha256(verifier.encode()).digest())


def test_token_file_is_not_readable_as_text(tmp_path):
    raw = acc.seal(b'{"token": "secret-token-value"}')
    assert b"secret-token-value" not in raw
    assert acc.unseal(raw) == b'{"token": "secret-token-value"}'


def test_whole_browser_sign_in_then_next_start_needs_nothing(hub, tmp_path):
    a = make(hub, tmp_path)
    assert a.check() == acc.LOGIN
    url, waiter, verifier = a.begin_login()
    assert url.startswith("https://obs-hub.invalid/mirror_login.html?")
    assert verifier not in url                                   # only the challenge travels
    assert hub.browser(url, state_override="x" * 32) == 400      # someone else's state: refused
    assert hub.browser(url) == 200
    code = waiter.wait(5)
    waiter.close()
    a.finish_login(code, verifier)
    assert a.username == "alice"
    token = a.session.token
    assert token.encode() not in (tmp_path / "account.dat").read_bytes()

    b = make(hub, tmp_path)                                      # the next start of the app
    assert b.check() == acc.OK and b.session.tier == "ultra"

    b.logout()
    assert token not in hub.tokens and not (tmp_path / "account.dat").exists()


def test_a_code_is_useless_without_the_verifier(hub, tmp_path):
    a = make(hub, tmp_path)
    url, waiter, _ = a.begin_login()
    hub.browser(url)
    code = waiter.wait(5)
    waiter.close()
    with pytest.raises(acc.AccountError):
        a.finish_login(code, acc.new_pkce()[0])
    assert a.session is None


def test_revoked_offline_and_switched_off(hub, tmp_path):
    clock = [1_000_000.0]
    a = make(hub, tmp_path, now=lambda: clock[0])
    url, waiter, verifier = a.begin_login()
    hub.browser(url)
    a.finish_login(waiter.wait(5), verifier)
    waiter.close()

    hub.down = True                                              # server trouble: last answer counts
    clock[0] += 6 * 24 * 3600
    assert a.check() == acc.OK
    clock[0] += 2 * 24 * 3600
    assert a.check() == acc.OFFLINE                              # …for 7 days only
    hub.down = False
    hub.off = True
    assert a.check() == acc.OFF
    hub.off = False
    hub.tokens.clear()                                           # signed out elsewhere / expired
    assert a.check() == acc.LOGIN and a.session is None


def test_dialog_stays_hidden_when_already_signed_in(hub, tmp_path):
    a = make(hub, tmp_path)
    url, waiter, verifier = a.begin_login()
    hub.browser(url)
    a.finish_login(waiter.wait(5), verifier)
    waiter.close()
    dlg = LoginDialog(make(hub, tmp_path), opener=lambda u: None)
    t0 = time.monotonic()
    assert dlg.run() is True
    assert not dlg.isVisible() and time.monotonic() - t0 < 5


def test_dialog_sign_in_with_the_browser(hub, tmp_path):
    a = make(hub, tmp_path)
    opened = []

    def browser(url):
        opened.append(url)
        threading.Thread(target=hub.browser, args=(url,), daemon=True).start()

    dlg = LoginDialog(a, opener=browser)
    QTimer.singleShot(50, dlg.start_login)                      # the streamer presses the button
    QTimer.singleShot(8000, dlg.reject)                         # safety net
    assert dlg.exec() == QDialog.Accepted
    assert len(opened) == 1 and a.username == "alice"


def test_quit_on_the_sign_in_window_means_no_app(hub, tmp_path):
    dlg = LoginDialog(make(hub, tmp_path), opener=lambda u: None)
    QTimer.singleShot(1200, dlg.reject)
    assert dlg.run() is False
