# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (English/Thai menus, language switch,
# OBS Browser Source and preview/GPU items, full-resolution screenshots).
"""Actions shared by both window modes: screenshot, sound, name, USB, log, about, OBS.

Mixin: the window must have `_cfg`, `_log_provider`, the signals `config_changed`,
`restart_requested`, `mode_requested` and the property `screenshot_image`.
"""
from __future__ import annotations

import os
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import (QApplication, QDialog, QInputDialog, QMenu, QMessageBox,
                               QPlainTextEdit, QVBoxLayout)

from .about_dialog import AboutDialog
from .i18n import T, current

SCREENSHOT_DIR = Path.home() / "Pictures" / "Obsidian Mirror"
USB_HELP = (
    "Mirroring over a cable — no Wi‑Fi or router needed:\n\n"
    "1. On the iPhone: Settings → Personal Hotspot → “Allow Others to Join” — on.\n"
    "2. Connect the iPhone to the PC with a cable and tap “Trust” on the iPhone.\n"
    "3. After a few seconds a green “USB” badge appears in the window.\n"
    "4. Control Center → Screen Mirroring → “{name}”.\n\n"
    "Apple's driver is needed (the Apple Devices app from Microsoft Store, or iTunes).\n"
    "The video goes straight over the cable and uses no mobile data. If Windows starts "
    "using the iPhone for internet, turn off Cellular Data on the iPhone.\n\n"
    "{state}"
)
MODE_NAMES = {"phone": "View: phone frame", "window": "View: plain window"}
LANGUAGE_NAMES = {"auto": "Automatic (Windows)", "th": "ไทย", "en": "English"}
SOURCE_NAMES = {"iphone": "iPhone (AirPlay, Wi‑Fi or cable)", "android": "Android (USB cable or Wi‑Fi) · beta"}
PREVIEW_MODES = {
    "auto": "Preview: show 1 minute after connecting, then hide (lightest)",
    "on": "Preview: always show",
    "off": "Preview: never show",
}
CAMERA_HELP = (
    "The phone picture becomes a webcam called “Obsidian Mirror Camera”.\n\n"
    "TikTok LIVE Studio: Add source → Camera → Obsidian Mirror Camera (pick 1080×1920 portrait here).\n"
    "Discord / Zoom / Meet: choose it as the camera in video settings.\n\n"
    "Picture only — the sound does not go through the camera.\n"
    "Using OBS? The OBS link is lighter and sharper than the camera."
)
CAMERA_NAMES = {
    "off": "Off",
    "720p": "1280×720 landscape (most apps)",
    "1080p": "1920×1080 landscape",
    "portrait": "1080×1920 portrait (TikTok LIVE Studio)",
}
CAMERA_SOURCE_NAMES = {
    "mirror": "Picture: the mirrored phone screen",
    "phone": "Picture: phone camera only, no buttons (scan a QR)",
}
FPS_CHOICES = {30: "30 fps — light (recommended)", 60: "60 fps — smoothest, for a strong PC"}


class LogDialog(QDialog):
    def __init__(self, lines: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(T("UxPlay log"))
        self.resize(760, 420)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setPlainText("\n".join(lines))
        lay = QVBoxLayout(self)
        lay.addWidget(self.text)

    def append(self, line: str) -> None:
        self.text.appendPlainText(line)


class CommonActions:
    _link = None
    _log_dialog: LogDialog | None = None
    _web = None                 # WebSource, set by the app (OBS link)
    _full_image = None          # callable → full-resolution QImage, set by the app
    _peek_preview = None        # callable: show the picture for a minute, set by the app
    _updates = None             # UpdateController, set by the app
    _show_phone_cam = None      # callable: the phone-camera QR dialog, set by the app
    _phone_state = None         # callable → "live 720x1280" etc. for feedback, set by the app

    # --- settings -----------------------------------------------------------------
    def _update_config(self, **changes) -> None:
        self._cfg = self._cfg.with_changes(**changes)
        self.config_changed.emit(self._cfg)

    def on_device_name_changed(self, name: str) -> None:
        """Overridden by the window to refresh its labels."""

    def window_title(self) -> str:
        return f"Obsidian Mirror — {self._cfg.device_name}"

    # --- shared part of the menu ---------------------------------------------------
    def add_common_menu(self, menu: QMenu) -> None:
        upd = self._updates
        if upd is not None and upd.latest is not None:
            menu.addAction(T("⬆ Update to version {version}…").format(version=upd.latest.version), upd.show)
            menu.addSeparator()
        phone = menu.addMenu(T("Phone: {name}").format(name=T(SOURCE_NAMES[self._cfg.source])))
        group_src = QActionGroup(phone)
        for key, title in SOURCE_NAMES.items():
            act = QAction(T(title), phone, checkable=True, checked=self._cfg.source == key)
            act.triggered.connect(lambda _=False, k=key: self._update_config(source=k))
            group_src.addAction(act)
            phone.addAction(act)
        phone.addSeparator()
        phone.addAction(T("Connect Android over Wi‑Fi (QR code)…"), self.pair_android_wifi)
        mode = menu.addMenu(T("Window view"))
        for key, title in MODE_NAMES.items():
            act = QAction(T(title), mode, checkable=True, checked=self._cfg.view_mode == key)
            act.triggered.connect(lambda _=False, k=key: self.mode_requested.emit(k))
            mode.addAction(act)
        rate = menu.addMenu(T("Frame rate: {fps} fps").format(fps=self._cfg.fps))
        group_rate = QActionGroup(rate)
        for fps, title in FPS_CHOICES.items():
            act = QAction(T(title), rate, checkable=True, checked=self._cfg.fps == fps)
            act.triggered.connect(lambda _=False, v=fps: self._set_fps(v))
            group_rate.addAction(act)
            rate.addAction(act)
        self._add_obs_menu(menu)
        self._add_camera_menu(menu)
        lang = menu.addMenu(T("Language / ภาษา"))
        group = QActionGroup(lang)
        for key, title in LANGUAGE_NAMES.items():
            act = QAction(T(title), lang, checkable=True, checked=self._cfg.language == key)
            act.triggered.connect(lambda _=False, k=key: self._update_config(language=k))
            group.addAction(act)
            lang.addAction(act)
        menu.addSeparator()
        menu.addAction(T("Screenshot  (Ctrl+S)"), self.save_screenshot)
        menu.addAction(T("Open screenshots folder"), self.open_screenshot_dir)
        sound = QAction(T("Sound on PC"), menu, checkable=True, checked=self._cfg.audio_enabled)
        sound.toggled.connect(self._toggle_audio)
        menu.addAction(sound)
        menu.addAction(T("Receiver name…"), self._rename)
        menu.addAction(T("Cable connection (USB)…"), self.show_usb_help)
        menu.addSeparator()
        menu.addAction(T("Restart receiver"), self.restart_requested.emit)
        menu.addAction(T("UxPlay log"), self.show_log)
        if upd is not None:
            updates = menu.addMenu(T("Updates"))
            updates.addAction(T("Check for updates now"), upd.check_now)
            auto = QAction(T("Check automatically"), updates, checkable=True,
                           checked=self._cfg.update_check)
            auto.toggled.connect(lambda on: self._update_config(update_check=on))
            updates.addAction(auto)
        menu.addAction(T("💬 Send feedback / report a problem…"), self.send_feedback)
        menu.addAction(T("About…"), lambda: AboutDialog(self).exec())
        menu.addAction(T("Quit  (Ctrl+Q)"), QApplication.quit)

    def _add_obs_menu(self, menu: QMenu) -> None:
        obs = menu.addMenu(T("OBS Browser Source"))
        web = self._web
        if web is not None and web.running:
            obs.addAction(T("Copy OBS link"), self.copy_obs_link)
            obs.addAction(T("Open the link in a browser"), lambda: webbrowser.open(web.url + "?debug=1"))
        else:
            off = obs.addAction(T("OBS link is off (port {port} is busy).").format(port=self._cfg.web_port))
            off.setEnabled(False)
        obs.addSeparator()
        group = QActionGroup(obs)
        for key, title in PREVIEW_MODES.items():
            act = QAction(T(title), obs, checkable=True, checked=self._cfg.preview_mode == key)
            act.triggered.connect(lambda _=False, k=key: self._update_config(preview_mode=k))
            group.addAction(act)
            obs.addAction(act)
        if self._peek_preview is not None and self._cfg.preview_mode == "auto":
            obs.addAction(T("Show preview for 1 minute"), self._peek_preview)
        obs.addSeparator()
        gpu = QAction(T("Use the graphics card (needs restart of mirroring)"), obs, checkable=True,
                      checked=self._cfg.use_gpu)
        gpu.toggled.connect(lambda on: self._update_config(use_gpu=on))
        obs.addAction(gpu)

    def _add_camera_menu(self, menu: QMenu) -> None:
        from .virtual_camera import is_registered
        cam = menu.addMenu(T("Virtual camera: {state}").format(state=T(CAMERA_NAMES[self._cfg.camera])))
        if not is_registered():
            off = cam.addAction(T("The camera is not installed (run native\\register_camera.ps1)."))
            off.setEnabled(False)
            return
        group = QActionGroup(cam)
        for key, label in CAMERA_NAMES.items():
            act = QAction(T(label), cam, checkable=True, checked=self._cfg.camera == key)
            act.triggered.connect(lambda _=False, k=key: self._update_config(camera=k))
            group.addAction(act)
            cam.addAction(act)
        cam.addSeparator()
        src = QActionGroup(cam)
        for key, label in CAMERA_SOURCE_NAMES.items():
            act = QAction(T(label), cam, checkable=True, checked=self._cfg.camera_source == key)
            act.triggered.connect(lambda _=False, k=key: self._pick_camera_source(k))
            src.addAction(act)
            cam.addAction(act)
        if self._cfg.camera_source == "phone" and self._show_phone_cam is not None:
            show = cam.addAction(T("Show the QR for the phone…"), self._show_phone_cam)
            show.setEnabled(self._cfg.camera != "off")
        cam.addSeparator()
        cam.addAction(T("How to use the camera…"), self.show_camera_help)

    def _pick_camera_source(self, key: str) -> None:
        # the phone camera needs the camera on: turn it on at the usual size
        changes = {"camera_source": key}
        if key == "phone" and self._cfg.camera == "off":
            changes["camera"] = "720p"
        self._update_config(**changes)

    def show_camera_help(self) -> None:
        QMessageBox.information(self, T("Virtual camera"), T(CAMERA_HELP))

    def copy_obs_link(self) -> None:
        if self._web is None:
            return
        QGuiApplication.clipboard().setText(self._web.url)
        QMessageBox.information(self, T("OBS Browser Source"), T(
            "Link copied: {url}\nIn OBS: Sources → + → Browser → paste it as URL, width 1080, height 1920."
        ).format(url=self._web.url))

    def pair_android_wifi(self) -> None:
        """Show the QR code; switches to Android first so the paired phone is picked up."""
        from .android_source import find_adb
        from .wifi_dialog import WifiPairDialog
        adb = find_adb(self._cfg)
        if adb is None:
            QMessageBox.warning(self, T("Connect Android over Wi‑Fi"),
                                T("adb not found. Run setup\\get_scrcpy.ps1"))
            return
        if self._cfg.source != "android":
            self._update_config(source="android")
        WifiPairDialog(adb, self).exec()

    def _set_fps(self, fps: int) -> None:
        if fps == self._cfg.fps:
            return
        self._update_config(fps=fps)
        self.restart_requested.emit()      # UxPlay tells the phone the limit when it connects
        QMessageBox.information(self, T("Frame rate"), T(
            "Frame rate set to {fps} fps.\nStart Screen Mirroring on the iPhone again to apply it."
        ).format(fps=fps))

    def _toggle_audio(self, on: bool) -> None:
        self._update_config(audio_enabled=on)
        self.restart_requested.emit()

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(self, T("Receiver name"), T("Name of this PC in Screen Mirroring:"),
                                        text=self._cfg.device_name)
        if ok and name.strip():
            self._update_config(device_name=name)
            self.setWindowTitle(self.window_title())
            self.on_device_name_changed(self._cfg.device_name)
            self.restart_requested.emit()

    # --- screenshots ----------------------------------------------------------------
    def _screenshot_source(self):
        """Full-resolution frame when the app can give one, else what is on screen."""
        return self.screenshot_image

    def save_screenshot(self) -> None:
        image = self._screenshot_source()
        if image is None:
            QMessageBox.information(self, T("Screenshot"), T("No active mirroring."))
            return
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, T("Screenshot"), T("Could not create the folder: {err}").format(err=exc))
            return
        path = SCREENSHOT_DIR / f"iPhone_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        if image.save(str(path)):
            QMessageBox.information(self, T("Screenshot"), T("Saved:\n{path}").format(path=path))
        else:
            QMessageBox.warning(self, T("Screenshot"), T("Could not save the file."))

    def open_screenshot_dir(self) -> None:
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(SCREENSHOT_DIR)  # noqa: S606 — opens our own folder in Explorer
        except OSError as exc:
            QMessageBox.warning(self, T("Screenshots"), T("Could not open the folder: {err}").format(err=exc))

    # --- USB and log ----------------------------------------------------------------
    def show_usb_help(self) -> None:
        link = self._link
        if link is None:
            state = T("Now: no direct connection to the iPhone.")
        else:
            how = T("by cable") if link.kind == "usb" else T("through the iPhone hotspot")
            state = T("Now: the iPhone is connected {how} ({iface}, PC IP {ip}).").format(
                how=how, iface=link.interface, ip=link.pc_ip)
        text = T("USB_HELP") if current() == "th" else USB_HELP
        QMessageBox.information(self, T("Cable connection"), text.format(name=self._cfg.device_name, state=state))

    def send_feedback(self) -> None:
        """Open the dashboard's support chat with this program's details (app/feedback.py)."""
        from .feedback import build_diag, feedback_url
        state = ""
        try:
            state = self._phone_state() if self._phone_state is not None else ""
        except Exception:                     # noqa: BLE001 - feedback must always open
            state = ""
        diag = build_diag(self._cfg, list(self._log_provider() or []), state)
        details = "\n".join(f"• {k}: {v}" for k, v in diag.items())
        box = QMessageBox(self)
        box.setWindowTitle(T("Send feedback"))
        box.setText(T("The dashboard opens at “แจ้งปัญหา” (log in if asked). Type what happened and press send — "
                      "the team answers you in that chat.\n\nThese details are attached so we can fix it faster "
                      "(no passwords, no addresses):"))
        box.setInformativeText(details)
        go = box.addButton(T("Open the dashboard"), QMessageBox.AcceptRole)
        box.addButton(T("Cancel"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            webbrowser.open(feedback_url(diag))

    def show_log(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = LogDialog(self._log_provider(), self)
        else:
            self._log_dialog.text.setPlainText("\n".join(self._log_provider()))
        self._log_dialog.show()
        self._log_dialog.raise_()

    def append_log(self, line: str) -> None:
        if self._log_dialog is not None:
            self._log_dialog.append(line)
