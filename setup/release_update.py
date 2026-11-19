# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Make the signed update note (latest.json) for a new installer.

  # once, on the release PC (the key never goes into git or onto a server):
  python setup/release_update.py keygen            # asks for a passphrase
  # a key made before passphrases, and its backups: encrypt in place (same key inside)
  python setup/release_update.py protect [more key files ...]
  # every release, after setup/build_installer.ps1:
  python setup/release_update.py sign dist/ObsidianMirror-Setup-1.4.1-obs.1.exe ^
      --url https://…/ObsidianMirror-Setup-1.4.1-obs.1.exe ^
      --th "แก้ภาพกระตุกตอน…" --en "Fixes stutter when…" [--min-version 1.4.0-obs.3] ^
      --out dist/latest.json
  # then upload the installer to --url and latest.json to the update address
  # (app/updater.py DEFAULT_URL). Upload the installer first.

The key file is encrypted with a passphrase that is typed each time and saved nowhere,
so a stolen file alone cannot sign. Forget the passphrase = the key is gone (keep it on paper).
The version comes from app/__init__.py. `verify latest.json` checks a note like the app does.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KEY_FILE = Path(os.environ.get("OBSIDIAN_MIRROR_SIGNING_KEY")
                or Path.home() / ".obsidian_mirror" / "update_signing_key.pem")
MIN_PASSPHRASE = 12


def keygen(args, ask=getpass.getpass) -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = Path(args.key)
    if path.exists():
        print(f"{path} already exists — not replacing it (old installs trust that key).")
        return 1
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(locked_pem(key, new_passphrase(ask)))
    print(f"Private key: {path}  (back it up somewhere safe and offline)")
    print("Public key for app/updater.py TRUSTED_KEYS:")
    print(public_b64(key))
    return 0


def public_b64(key) -> str:
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def new_passphrase(ask=getpass.getpass) -> bytes:
    """Asked twice; never echoed, never saved."""
    while True:
        a = ask(f"New passphrase for the signing key (at least {MIN_PASSPHRASE} characters): ")
        if len(a) < MIN_PASSPHRASE:
            print("Too short.")
            continue
        if ask("Type it again: ") != a:
            print("They do not match.")
            continue
        return a.encode("utf-8")


def locked_pem(key, passphrase: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.BestAvailableEncryption(passphrase))


def is_locked(data: bytes) -> bool:
    return b"ENCRYPTED PRIVATE KEY" in data


def load_key(path, ask=getpass.getpass, allow_plain=False):
    from cryptography.hazmat.primitives import serialization
    data = Path(path).read_bytes()
    if not is_locked(data):
        if not allow_plain:
            raise SystemExit(f"{path} has no passphrase. Run first:  python setup/release_update.py protect")
        return serialization.load_pem_private_key(data, password=None)
    for _ in range(3):
        try:
            return serialization.load_pem_private_key(
                data, password=ask(f"Passphrase for {path}: ").encode("utf-8"))
        except ValueError:
            print("Wrong passphrase.")
    raise SystemExit("Wrong passphrase 3 times.")


def protect(args, ask=getpass.getpass) -> int:
    """Encrypt plain key files in place. All files must hold the trusted key; checked before writing."""
    from cryptography.hazmat.primitives import serialization
    from app.updater import TRUSTED_KEYS
    paths = [Path(args.key)] + [Path(p) for p in args.paths]
    if any(is_locked(p.read_bytes()) for p in paths):
        print("A file already has a passphrase — nothing changed.")
        return 1
    keys = [load_key(p, ask, allow_plain=True) for p in paths]
    pubs = {public_b64(k) for k in keys}
    if len(pubs) != 1 or next(iter(pubs)) not in TRUSTED_KEYS:
        print("These files do not all hold the key in app/updater.py TRUSTED_KEYS — nothing changed.")
        return 1
    passphrase = new_passphrase(ask)
    for path, key in zip(paths, keys):
        new = locked_pem(key, passphrase)
        back = serialization.load_pem_private_key(new, password=passphrase)
        assert public_b64(back) == public_b64(key)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(new)
        os.chmod(path, 0o600)                       # backups are read-only
        os.replace(tmp, path)
        os.chmod(path, 0o400)
        print(f"Locked: {path}  sha256 {hashlib.sha256(new).hexdigest().upper()}")
    return 0


def make_note(key, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"payload": base64.b64encode(body).decode(), "sig": base64.b64encode(key.sign(body)).decode()}


def sign(args, ask=getpass.getpass) -> int:
    from app import __version__
    from app.updater import APP_ID, TRUSTED_KEYS, parse_note
    exe = Path(args.installer)
    data = exe.read_bytes()                          # before the passphrase: fail early on a bad path
    key = load_key(args.key, ask)
    if public_b64(key) not in TRUSTED_KEYS:
        print("This key is not in app/updater.py TRUSTED_KEYS — installed copies would refuse it.")
        return 1
    payload = {"app": APP_ID, "version": args.version or __version__, "url": args.url,
               "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
               "min_version": args.min_version or "", "notes": {"th": args.th, "en": args.en},
               "published": dt.date.today().isoformat()}
    note = make_note(key, payload)
    parse_note(json.dumps(note).encode())          # the app must accept it
    Path(args.out).write_text(json.dumps(note, indent=1), encoding="utf-8")
    print(f"{args.out}: {payload['version']} · {payload['size']:,} bytes · sha256 {payload['sha256'][:16]}…")
    return 0


def verify(args) -> int:
    from app.updater import parse_note
    info = parse_note(Path(args.note).read_bytes())
    print(f"OK: {info.version} · {info.size:,} bytes · {info.url}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Thai Windows console = cp874
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=str(KEY_FILE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen").set_defaults(fn=keygen)
    pr = sub.add_parser("protect", help="add a passphrase to --key and these backup copies")
    pr.add_argument("paths", nargs="*")
    pr.set_defaults(fn=protect)
    s = sub.add_parser("sign")
    s.add_argument("installer")
    s.add_argument("--url", required=True)
    s.add_argument("--th", required=True)
    s.add_argument("--en", required=True)
    s.add_argument("--min-version", default="")
    s.add_argument("--version", default="", help="default: app/__init__.py")
    s.add_argument("--out", default="latest.json")
    s.set_defaults(fn=sign)
    v = sub.add_parser("verify")
    v.add_argument("note")
    v.set_defaults(fn=verify)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
