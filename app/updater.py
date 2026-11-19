# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""In-app updates: check a signed note, download the new installer, run it, restart.

The note (latest.json) is {"payload": <base64 JSON>, "sig": <base64 Ed25519 signature
of the payload bytes>}. Only notes signed by a key in TRUSTED_KEYS are believed, so a
changed file on the web server cannot push a program to anyone. The payload names the
installer by its SHA-256 and size; the download must match both.

    payload = {"app": "obsidian-mirror", "version": "1.4.1-obs.1",
               "url": "https://…/ObsidianMirror-Setup-1.4.1-obs.1.exe",
               "size": 123, "sha256": "…", "min_version": "",
               "notes": {"th": "…", "en": "…"}, "published": "2026-11-20"}

Signing notes: setup/release_update.py. Installing: the Inno Setup installer is run with
/SILENT, it closes this program, installs over it and starts it again ([Run] WizardSilent).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from .paths import APP_NAME, IS_FROZEN

log = logging.getLogger(__name__)

APP_ID = "obsidian-mirror"
DEFAULT_URL = "https://obs-hub.web.app/mirror/latest.json"
# Public keys (raw Ed25519, base64). The private key never leaves the release PC.
# More than one is allowed so the key can be changed without stranding old installs.
TRUSTED_KEYS = ("8F1cLAoPIMa92VQPhfncIoAW0KllP4VonrKyoZ5FznI=",)
NOTE_LIMIT = 64 * 1024
INSTALLER_LIMIT = 600 * 1024 * 1024
CHECK_EVERY_MS = 6 * 3600 * 1000
FIRST_CHECK_MS = 20_000
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
# Lets the source build run a (signed) installer too — only for trying the flow on a dev PC.
DEV_INSTALL_ENV = "OBSIDIAN_MIRROR_DEV_INSTALL"


class UpdateError(Exception):
    pass


def version_key(text: str) -> tuple[int, ...]:
    """"1.4.0-obs.2" → (1, 4, 0, 2); "1.4.0" → (1, 4, 0, 0). Anything odd → ()."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-obs\.(\d+))?", text.strip())
    return tuple(int(x or 0) for x in m.groups()) if m else ()


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, cur = version_key(candidate), version_key(current)
    return bool(new) and bool(cur) and new > cur


def can_install() -> bool:
    return IS_FROZEN or os.environ.get(DEV_INSTALL_ENV) == "1"


def updates_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    size: int
    sha256: str
    notes: dict = field(default_factory=dict)
    min_version: str = ""
    published: str = ""

    @property
    def required(self) -> bool:
        """The running version is too old to keep using (e.g. a broken server change)."""
        return bool(self.min_version) and is_newer(self.min_version)

    def notes_for(self, lang: str) -> str:
        return str(self.notes.get(lang) or self.notes.get("en") or self.notes.get("th") or "")


def _verify(note: dict, keys=None) -> bytes:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        payload = base64.b64decode(note["payload"], validate=True)
        sig = base64.b64decode(note["sig"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("The update note is damaged.") from exc
    for key in (TRUSTED_KEYS if keys is None else keys):
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(sig, payload)
            return payload
        except InvalidSignature:
            continue
    raise UpdateError("The update note is not signed by Obsidian Stream Hub.")


def _safe_url(url: str) -> bool:
    if url.startswith("https://"):
        return True
    # Plain http only to this PC (tests, trying a release before upload).
    return re.match(r"http://(127\.0\.0\.1|localhost)(:\d+)?/", url) is not None


def parse_note(raw: bytes, keys=None) -> UpdateInfo:
    """Check the signature and the fields; return what the note offers."""
    try:
        note = json.loads(raw)
        if not isinstance(note, dict):
            raise ValueError
    except ValueError as exc:
        raise UpdateError("The update note is damaged.") from exc
    try:
        data = json.loads(_verify(note, keys))
        info = UpdateInfo(version=str(data["version"]), url=str(data["url"]), size=int(data["size"]),
                          sha256=str(data["sha256"]).lower(),
                          notes=data.get("notes") if isinstance(data.get("notes"), dict) else {},
                          min_version=str(data.get("min_version") or ""),
                          published=str(data.get("published") or ""))
        app = data["app"]
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("The update note is damaged.") from exc
    if (app != APP_ID or not version_key(info.version) or not _safe_url(info.url)
            or not re.fullmatch(r"[0-9a-f]{64}", info.sha256) or not 0 < info.size <= INSTALLER_LIMIT):
        raise UpdateError("The update note is damaged.")
    return info


def _open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"ObsidianMirror/{__version__}",
                                               "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_note(url: str, keys=None, timeout: float = 10.0) -> UpdateInfo:
    if not _safe_url(url):
        raise UpdateError("The update address must use https.")
    try:
        with _open(url, timeout) as resp:
            raw = resp.read(NOTE_LIMIT + 1)
    except OSError as exc:
        raise UpdateError("Could not reach the update server.") from exc
    if len(raw) > NOTE_LIMIT:
        raise UpdateError("The update note is damaged.")
    return parse_note(raw, keys)


def download(info: UpdateInfo, progress=None, cancel: threading.Event | None = None,
             folder: Path | None = None, timeout: float = 20.0) -> Path:
    """Download the installer to the updates folder and check its size and SHA-256.
    A partial or wrong file is deleted; only a checked file keeps its final name."""
    folder = folder or updates_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"ObsidianMirror-Setup-{info.version}.exe")
    final, part = folder / name, folder / (name + ".part")
    if final.is_file() and final.stat().st_size == info.size and _sha256(final) == info.sha256:
        if progress:
            progress(info.size, info.size)
        return final
    digest, done = hashlib.sha256(), 0
    try:
        with _open(info.url, timeout) as resp, open(part, "wb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Cancelled.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > info.size:
                    raise UpdateError("The download does not match the update note.")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, info.size)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise UpdateError("The download stopped. Check the internet and try again.") from exc
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    if done != info.size or digest.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("The download does not match the update note.")
    os.replace(part, final)
    return final


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_old(keep: str = "", folder: Path | None = None) -> None:
    """Remove installers left from earlier updates (the running version is installed)."""
    try:
        for f in (folder or updates_dir()).iterdir():
            if f.is_file() and not (keep and keep in f.name):
                f.unlink(missing_ok=True)
    except OSError:
        pass


def run_installer(path: Path) -> None:
    """Start the installer. It asks Windows for admin rights (UAC) by itself."""
    if sys.platform != "win32":
        raise UpdateError("Updates install only on Windows.")
    import ctypes
    params = " ".join(INSTALLER_ARGS)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", str(path), params, str(path.parent), 1)
    if rc <= 32:
        raise UpdateError("Windows did not start the installer (permission refused?).")


class UpdateChecker(QObject):
    """Checks in a thread; results come back as Qt signals on the GUI thread."""
    available = Signal(object, bool)        # UpdateInfo, asked by the user
    up_to_date = Signal(bool)
    failed = Signal(str, bool)

    def __init__(self, url: str = DEFAULT_URL, keys=None) -> None:
        super().__init__()
        self.url = url
        self.keys = keys
        self.latest: UpdateInfo | None = None
        self._busy = threading.Lock()

    def check(self, manual: bool = False) -> None:
        if not self._busy.acquire(blocking=False):
            return
        threading.Thread(target=self._run, args=(manual,), name="update-check", daemon=True).start()

    def _run(self, manual: bool) -> None:
        try:
            info = fetch_note(self.url, self.keys)
            if is_newer(info.version):
                self.latest = info
                self.available.emit(info, manual)
            else:
                self.up_to_date.emit(manual)
        except UpdateError as exc:
            log.info("update check: %s", exc)
            self.failed.emit(str(exc), manual)
        except Exception as exc:     # never let a check take the program down
            log.exception("update check failed")
            self.failed.emit(f"{type(exc).__name__}: {exc}", manual)
        finally:
            self._busy.release()
