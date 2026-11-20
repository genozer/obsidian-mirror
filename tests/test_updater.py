# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""In-app updates against a local web server, signed with a throwaway test key."""
from __future__ import annotations

import hashlib
import http.server
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtWidgets import QApplication

from app import __version__, updater
from app.config import AppConfig

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "setup"))
import release_update  # noqa: E402

KEY = Ed25519PrivateKey.generate()
KEYS = (release_update.public_b64(KEY),)
INSTALLER = b"MZ fake installer " * 5000


def payload(**over) -> dict:
    p = {"app": "obsidian-mirror", "version": "9.0.0-obs.1", "url": "https://example.invalid/x.exe",
         "size": len(INSTALLER), "sha256": hashlib.sha256(INSTALLER).hexdigest(),
         "min_version": "", "notes": {"th": "แก้ภาพกระตุก", "en": "Fixes stutter"},
         "published": "2026-11-20"}
    p.update(over)
    return p


def note(key=KEY, **over) -> bytes:
    return json.dumps(release_update.make_note(key, payload(**over))).encode()


@pytest.fixture
def web(tmp_path):
    """Serves files from a folder on 127.0.0.1; returns (base url, folder)."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path), **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", tmp_path
    srv.shutdown()
    srv.server_close()


def publish(web, **over) -> str:
    base, folder = web
    (folder / "setup.exe").write_bytes(INSTALLER)
    (folder / "latest.json").write_bytes(note(url=f"{base}/setup.exe", **over))
    return f"{base}/latest.json"


def wait_for(cond, seconds=10.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


# --- versions and the signed note ----------------------------------------------------
def test_versions_compare_as_numbers():
    assert updater.version_key("1.4.0-obs.12") == (1, 4, 0, 12)
    assert updater.is_newer("1.4.0-obs.10", "1.4.0-obs.9")
    assert updater.is_newer("1.4.1", "1.4.0-obs.9")
    assert not updater.is_newer("1.4.0-obs.1", "1.4.0-obs.1")
    assert not updater.is_newer("1.3.9-obs.99", "1.4.0-obs.1")
    assert not updater.is_newer("2.0 beta", "1.0.0") and not updater.is_newer("9.9.9", "odd")


def test_the_running_version_is_understood():
    assert updater.version_key(__version__)


def test_good_note_is_accepted():
    info = updater.parse_note(note(), KEYS)
    assert info.version == "9.0.0-obs.1" and info.size == len(INSTALLER)
    assert info.notes_for("th") == "แก้ภาพกระตุก" and info.notes_for("xx") == "Fixes stutter"
    assert not info.required
    assert updater.parse_note(note(min_version="9.0.0"), KEYS).required


def test_changed_or_foreign_notes_are_refused():
    import base64
    n = json.loads(note())
    body = json.loads(base64.b64decode(n["payload"]))
    body["url"] = "https://evil.invalid/other.exe"            # changed on the server
    n["payload"] = base64.b64encode(json.dumps(body).encode()).decode()
    with pytest.raises(updater.UpdateError, match="not signed"):
        updater.parse_note(json.dumps(n).encode(), KEYS)
    with pytest.raises(updater.UpdateError, match="not signed"):          # someone else's key
        updater.parse_note(note(key=Ed25519PrivateKey.generate()), KEYS)
    with pytest.raises(updater.UpdateError, match="not signed"):          # our real key ≠ test key
        updater.parse_note(note())
    for bad in (dict(app="other"), dict(url="http://example.com/x.exe"), dict(sha256="abc"),
                dict(size=0), dict(version="latest")):
        with pytest.raises(updater.UpdateError, match="damaged"):
            updater.parse_note(note(**bad), KEYS)
    for raw in (b"", b"[]", b"{not json", b'{"payload": "!!", "sig": "x"}'):
        with pytest.raises(updater.UpdateError, match="damaged"):
            updater.parse_note(raw, KEYS)


PASS = "correct horse battery"


def answers(*said):
    """Stands in for getpass: hands out the typed answers in order."""
    it = iter(said)
    return lambda prompt="": next(it)


def sign_args(tmp_path, key_file):
    import argparse
    exe = tmp_path / "s.exe"
    exe.write_bytes(INSTALLER)
    return argparse.Namespace(key=str(key_file), installer=str(exe), url="https://x.invalid/s.exe",
                              th="ท", en="e", min_version="", version="", out=str(tmp_path / "l.json"))


def plain_key_file(tmp_path, key=KEY, name="k.pem"):
    from cryptography.hazmat.primitives import serialization
    f = tmp_path / name
    f.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return f


def test_release_tool_refuses_a_key_the_app_does_not_trust(tmp_path, capsys):
    key_file = tmp_path / "k.pem"
    key_file.write_bytes(release_update.locked_pem(KEY, PASS.encode()))
    assert release_update.sign(sign_args(tmp_path, key_file), ask=answers(PASS)) == 1
    assert "TRUSTED_KEYS" in capsys.readouterr().out


def test_signing_needs_the_passphrase(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    key_file = tmp_path / "k.pem"
    key_file.write_bytes(release_update.locked_pem(KEY, PASS.encode()))
    assert release_update.is_locked(key_file.read_bytes())
    with pytest.raises(SystemExit):                                     # 3 wrong tries
        release_update.sign(sign_args(tmp_path, key_file), ask=answers("a", "b", "c"))
    assert release_update.sign(sign_args(tmp_path, key_file), ask=answers("nope", PASS)) == 0
    updater.parse_note((tmp_path / "l.json").read_bytes(), keys=KEYS)


def test_enter_with_nothing_typed_asks_again_instead_of_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    key_file = tmp_path / "k.pem"
    key_file.write_bytes(release_update.locked_pem(KEY, PASS.encode()))
    # Enter twice, two wrong, then right: empty presses do not use up the 3 tries
    assert release_update.sign(sign_args(tmp_path, key_file), ask=answers("", "", "x", "y", PASS)) == 0
    assert "Nothing typed" in capsys.readouterr().out


def test_change_passphrase_keeps_the_same_key(tmp_path, monkeypatch):
    import argparse
    main, backup = tmp_path / "k.pem", tmp_path / "b.pem"
    for f in (main, backup):
        f.write_bytes(release_update.locked_pem(KEY, PASS.encode()))
    new = "a brand new passphrase"
    args = argparse.Namespace(key=str(main), paths=[str(backup)])
    assert release_update.change_passphrase(args, ask=answers(PASS, PASS, new, new)) == 0
    for f in (main, backup):
        with pytest.raises(SystemExit):                             # old one no longer opens it
            release_update.load_key(f, answers(PASS, PASS, PASS))
        assert release_update.public_b64(release_update.load_key(f, answers(new))) == KEYS[0]


def test_a_key_without_passphrase_is_not_used_for_signing(tmp_path):
    with pytest.raises(SystemExit, match="protect"):
        release_update.sign(sign_args(tmp_path, plain_key_file(tmp_path)), ask=answers())


def test_protect_locks_the_key_and_its_backups_with_the_same_key_inside(tmp_path, monkeypatch, capsys):
    import argparse
    import os
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    main, backup = plain_key_file(tmp_path), plain_key_file(tmp_path, name="backup.pem")
    os.chmod(backup, 0o400)                                             # backups are read-only
    args = argparse.Namespace(key=str(main), paths=[str(backup)])
    # too short, then a typo, then right
    assert release_update.protect(args, ask=answers("short", PASS, PASS + "x", PASS, PASS)) == 0
    for f in (main, backup):
        assert release_update.is_locked(f.read_bytes())
        assert release_update.public_b64(release_update.load_key(f, answers(PASS))) == KEYS[0]
    assert not list(tmp_path.glob("*.tmp"))
    assert release_update.protect(args, ask=answers()) == 1             # already locked: untouched


def test_protect_changes_nothing_when_the_files_hold_different_keys(tmp_path, monkeypatch):
    import argparse
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    main = plain_key_file(tmp_path)
    other = plain_key_file(tmp_path, Ed25519PrivateKey.generate(), "other.pem")
    before = main.read_bytes(), other.read_bytes()
    assert release_update.protect(argparse.Namespace(key=str(main), paths=[str(other)]), ask=answers()) == 1
    assert (main.read_bytes(), other.read_bytes()) == before


# --- download ----------------------------------------------------------------------------
def test_check_and_download_from_the_server(web, tmp_path):
    url = publish(web)
    info = updater.fetch_note(url, KEYS)
    seen = []
    path = updater.download(info, progress=lambda d, t: seen.append(d), folder=tmp_path / "dl")
    assert path.read_bytes() == INSTALLER and seen[-1] == len(INSTALLER)
    assert not list((tmp_path / "dl").glob("*.part"))
    # Already downloaded and still matching: no second download.
    (web[1] / "setup.exe").unlink()
    assert updater.download(info, folder=tmp_path / "dl") == path


@pytest.mark.parametrize("served", [INSTALLER[:-1] + b"X", INSTALLER + b"more", INSTALLER[:100]])
def test_wrong_download_is_thrown_away(web, tmp_path, served):
    info = updater.fetch_note(publish(web), KEYS)
    (web[1] / "setup.exe").write_bytes(served)       # swapped / bigger / cut short
    dl = tmp_path / "dl"
    dl.mkdir()
    with pytest.raises(updater.UpdateError, match="does not match"):
        updater.download(info, folder=dl)
    assert list(dl.iterdir()) == []


def test_unreachable_server_and_plain_http(tmp_path):
    with pytest.raises(updater.UpdateError, match="reach"):
        updater.fetch_note("http://127.0.0.1:9/latest.json", KEYS, timeout=2)
    with pytest.raises(updater.UpdateError, match="https"):
        updater.fetch_note("http://example.com/latest.json", KEYS)


def test_old_installers_are_cleaned(tmp_path):
    for n in ("ObsidianMirror-Setup-1.4.0-obs.1.exe", "ObsidianMirror-Setup-1.4.0-obs.2.exe", "x.part"):
        (tmp_path / n).write_bytes(b"x")
    updater.clean_old(keep="1.4.0-obs.2", folder=tmp_path)
    assert [f.name for f in tmp_path.iterdir()] == ["ObsidianMirror-Setup-1.4.0-obs.2.exe"]


# --- the window and when it appears -----------------------------------------------------
def test_dialog_downloads_checks_and_runs_the_installer(web, monkeypatch, tmp_path):
    from app.update_dialog import UpdateDialog
    monkeypatch.setattr(updater, "can_install", lambda: True)
    monkeypatch.setattr(updater, "updates_dir", lambda: tmp_path)
    info = updater.fetch_note(publish(web), KEYS)
    ran, quit_ = [], []
    dlg = UpdateDialog(info, launch=ran.append, quit_app=lambda: quit_.append(True))
    dlg.start()
    assert wait_for(lambda: quit_), dlg.status.text()
    assert ran[0].read_bytes() == INSTALLER and dlg.installed


def test_dialog_does_not_install_a_bad_file(web, monkeypatch, tmp_path):
    from app.update_dialog import UpdateDialog
    monkeypatch.setattr(updater, "can_install", lambda: True)
    monkeypatch.setattr(updater, "updates_dir", lambda: tmp_path)
    info = updater.fetch_note(publish(web), KEYS)
    (web[1] / "setup.exe").write_bytes(b"MZ evil")
    ran = []
    dlg = UpdateDialog(info, launch=ran.append, quit_app=lambda: None)
    dlg.start()
    assert wait_for(lambda: dlg.go.isEnabled())
    assert ran == [] and "does not match" in dlg.status.text()


def test_source_build_cannot_press_install(monkeypatch):
    from app.update_dialog import UpdateDialog
    monkeypatch.setattr(updater, "can_install", lambda: False)
    dlg = UpdateDialog(updater.parse_note(note(), KEYS))
    assert not dlg.go.isEnabled() and "git pull" in dlg.status.text()


class FakeDisplay:
    def __init__(self, streaming=False):
        self.cfg = AppConfig()
        self.streaming = streaming
        self.window = None
        self.saved = []

    def on_config(self, cfg):
        self.cfg = cfg
        self.saved.append(cfg)


def controller(web, display, **over):
    from app.update_dialog import UpdateController
    upd = UpdateController(display, url=publish(web, **over), keys=KEYS)
    shown = []
    upd.show = lambda: shown.append(upd.latest.version)
    return upd, shown


def test_auto_check_offers_when_idle(web):
    upd, shown = controller(web, FakeDisplay())
    upd.auto_check()
    assert wait_for(lambda: shown) and shown == ["9.0.0-obs.1"]


def test_never_during_a_stream_only_after_the_phone_stays_off(web, monkeypatch):
    from app import update_dialog
    monkeypatch.setattr(update_dialog, "IDLE_MS", 200)
    disp = FakeDisplay(streaming=True)
    upd, shown = controller(web, disp)
    upd._idle.setInterval(200)
    upd.auto_check()
    assert wait_for(lambda: upd.latest is not None)
    assert not wait_for(lambda: shown, 0.5)          # mirroring: menu only, no window
    disp.streaming = False
    upd.on_stream(False)                             # phone dropped…
    disp.streaming = True
    upd.on_stream(True)                              # …and came back within the wait
    assert not wait_for(lambda: shown, 0.6)
    disp.streaming = False
    upd.on_stream(False)
    assert wait_for(lambda: shown, 3)


def test_skipped_version_is_not_offered_again_but_required_is(web):
    disp = FakeDisplay()
    disp.cfg = disp.cfg.with_changes(update_skip="9.0.0-obs.1")
    upd, shown = controller(web, disp)
    upd.auto_check()
    assert wait_for(lambda: upd.latest is not None) and not wait_for(lambda: shown, 0.5)
    upd.check_now()                                  # asking by hand always shows it
    assert wait_for(lambda: shown)
    upd2, shown2 = controller(web, disp, min_version="9.0.0")
    upd2.auto_check()
    assert wait_for(lambda: shown2)


def test_auto_check_can_be_turned_off(web):
    disp = FakeDisplay()
    disp.cfg = disp.cfg.with_changes(update_check=False)
    upd, shown = controller(web, disp)
    upd.auto_check()
    assert not wait_for(lambda: upd.latest is not None, 0.8)


def test_up_to_date_note_offers_nothing(web):
    upd, shown = controller(web, FakeDisplay(), version=__version__)
    done = []
    upd.checker.up_to_date.connect(lambda m: done.append(m))
    upd.auto_check()
    assert wait_for(lambda: done) and upd.latest is None and not shown
