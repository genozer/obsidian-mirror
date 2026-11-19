# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Sign in with an Obsidian Hub account (free on every plan; the app stays locked until then).

The browser does the login (Google works), the app never sees a password:
  1. make a random `verifier`, `challenge` = base64url(sha256(verifier)), a random `state`,
     and listen on 127.0.0.1:<random port>;
  2. open https://obs-hub.web.app/mirror_login.html?challenge=…&state=…&port=… ;
     the streamer presses "Allow" and the page sends the browser to
     http://127.0.0.1:<port>/callback?code=…&state=… ;
  3. trade code + verifier for this PC's token (POST /api/mirror/token).
A code seen by anyone else is useless without the verifier, which never leaves the app.
The token is kept with Windows DPAPI (only this Windows user can read it).
Each start asks the server if it still holds (POST /api/mirror/me); with no internet the
last good answer counts for OFFLINE_GRACE.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import platform
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .i18n import T
from .paths import user_data_dir

log = logging.getLogger(__name__)

# OBSIDIAN_MIRROR_API / _LOGIN_PAGE: point a dev build at a local server (lab/local_sandbox)
API_URL = os.environ.get("OBSIDIAN_MIRROR_API") or "https://obsidian-hub.duckdns.org:5000"
LOGIN_PAGE = os.environ.get("OBSIDIAN_MIRROR_LOGIN_PAGE") or "https://obs-hub.web.app/mirror_login.html"
ACCOUNT_PATH = user_data_dir() / "account.dat"
OFFLINE_GRACE = 7 * 24 * 3600
LOGIN_WAIT = 10 * 60
TIMEOUT = 10

# check() results
OK, LOGIN, OFF, OFFLINE = "ok", "login", "off", "offline"


class AccountError(Exception):
    pass


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_pkce() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(32))
    return verifier, b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# --- Windows DPAPI ---------------------------------------------------------------------
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    from ctypes import wintypes  # noqa: F401 - Windows only
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def seal(data: bytes) -> bytes:
    return b"D1" + _dpapi(data, True) if sys.platform == "win32" else b"P1" + data


def unseal(data: bytes) -> bytes:
    if data[:2] == b"D1":
        return _dpapi(data[2:], False)
    if data[:2] == b"P1":
        return data[2:]
    raise ValueError("unknown account file")


# --- the 127.0.0.1 callback ------------------------------------------------------------
class LoginWaiter:
    """Waits for the browser to come back with ?code=…&state=… (first good one wins)."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.code: str | None = None
        self.done = threading.Event()
        waiter = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # quiet
                pass

            def do_GET(self) -> None:  # noqa: N802
                url = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(url.query)
                code, state = (q.get("code") or [""])[0], (q.get("state") or [""])[0]
                good = (url.path == "/callback" and code and not waiter.done.is_set()
                        and hmac.compare_digest(state.encode(), waiter.state.encode()))
                if good:
                    waiter.code = code
                    waiter.done.set()
                text = (T("Signed in. You can close this tab and go back to Obsidian Mirror.") if good
                        else T("This sign-in link is not valid. Press \"Sign in\" in Obsidian Mirror again."))
                body = ("<!doctype html><meta charset='utf-8'><title>Obsidian Mirror</title>"
                        "<body style='font-family:Segoe UI,Tahoma,sans-serif;background:#0e1117;color:#e7eaf1;"
                        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                        f"<h2 style='max-width:520px;text-align:center'>{'✅' if good else '⚠️'} "
                        f"{text.replace('<', '&lt;')}</h2>").encode("utf-8")
                self.send_response(200 if good else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, name="login-callback", daemon=True).start()

    def wait(self, timeout: float = LOGIN_WAIT) -> str | None:
        self.done.wait(timeout)
        return self.code

    def close(self) -> None:
        self.done.set()
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass


@dataclass
class Session:
    token: str = ""
    username: str = ""
    tier: str = ""
    checked_at: float = 0.0


class Account:
    def __init__(self, path: Path = ACCOUNT_PATH, api: str = API_URL, page: str = LOGIN_PAGE,
                 now=time.time) -> None:
        self.path, self.api, self.page, self.now = Path(path), api.rstrip("/"), page, now
        self.session = self._load()

    # storage
    def _load(self) -> Session | None:
        try:
            d = json.loads(unseal(self.path.read_bytes()).decode("utf-8"))
            return Session(**{k: d[k] for k in ("token", "username", "tier", "checked_at") if k in d})
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001 - damaged or from another Windows user
            log.warning("account file unreadable: %s", exc)
            return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(seal(json.dumps(self.session.__dict__).encode("utf-8")))
        tmp.replace(self.path)

    def clear(self) -> None:
        self.session = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    @property
    def username(self) -> str:
        return self.session.username if self.session else ""

    # server
    def _post(self, route: str, body: dict | None = None, token: str = "") -> tuple[int, dict]:
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self.api + route, data=data, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": f"ObsidianMirror/{__version__}",
            **({"x-mirror-token": token} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def check(self) -> str:
        """OK · LOGIN (sign in needed) · OFF (switched off for this account) · OFFLINE (no answer, too long)."""
        s = self.session
        if not s or not s.token:
            return LOGIN
        try:
            code, j = self._post("/api/mirror/me", token=s.token)
        except (OSError, ValueError) as exc:
            log.info("account check: no answer (%s)", exc)
            return OK if self.now() - s.checked_at < OFFLINE_GRACE else OFFLINE
        if code == 200 and j.get("success"):
            u = j.get("user") or {}
            s.username, s.tier, s.checked_at = u.get("username", ""), u.get("tier", ""), self.now()
            self._save()
            return OK
        if code == 401:
            self.clear()
            return LOGIN
        if code == 403:
            return OFF
        return OK if self.now() - s.checked_at < OFFLINE_GRACE else OFFLINE   # server trouble

    def begin_login(self) -> tuple[str, LoginWaiter, str]:
        """Returns (browser URL, waiter, verifier)."""
        verifier, challenge = new_pkce()
        waiter = LoginWaiter(b64url(secrets.token_bytes(24)))
        url = self.page + "?" + urllib.parse.urlencode(
            {"challenge": challenge, "state": waiter.state, "port": waiter.port})
        return url, waiter, verifier

    def finish_login(self, code: str, verifier: str) -> None:
        try:
            status, j = self._post("/api/mirror/token", {"code": code, "verifier": verifier,
                                                         "device": platform.node()[:60]})
        except (OSError, ValueError) as exc:
            raise AccountError(T("Could not reach Obsidian Hub. Check the internet and try again.")) from exc
        if status == 403:
            raise AccountError(T("Phone Cast is switched off for this account."))
        if status != 200 or not j.get("success") or not j.get("token"):
            raise AccountError(T("Sign-in did not finish. Please try again."))
        u = j.get("user") or {}
        self.session = Session(j["token"], u.get("username", ""), u.get("tier", ""), self.now())
        self._save()

    def logout(self) -> None:
        if self.session and self.session.token:
            try:
                self._post("/api/mirror/logout", token=self.session.token)
            except (OSError, ValueError):
                pass   # the server forgets it after 90 days anyway
        self.clear()
