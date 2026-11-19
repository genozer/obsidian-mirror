# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Update window + when to show it (updater.py does the checking and downloading).

Never in the middle of a stream: a check that finds a new version while a phone is
mirroring waits until the phone has been disconnected for IDLE_MS.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from . import __version__
from . import updater
from .i18n import T, current

IDLE_MS = 2 * 60 * 1000
STYLE = ("QDialog { background: #1f1f23; } QLabel { color: #f4f4f5; }"
         "QLabel#muted { color: #a1a1aa; } QLabel#status { color: #c4b5fd; font-weight: 600; }"
         "QLabel#notes { background: #27272a; border-radius: 8px; padding: 10px; }"
         "QPushButton { background: #3f3f46; color: white; border: none; border-radius: 8px;"
         " padding: 7px 18px; } QPushButton:hover { background: #52525b; }"
         "QPushButton#primary { background: #7c3aed; } QPushButton#primary:hover { background: #8b5cf6; }"
         "QPushButton:disabled { background: #2e2e33; color: #71717a; }"
         "QProgressBar { background: #27272a; border: none; border-radius: 5px; height: 10px;"
         " color: transparent; } QProgressBar::chunk { background: #8b5cf6; border-radius: 5px; }")
ERRORS = (   # updater.py messages; shown through T()
    "The update note is damaged.",
    "The update note is not signed by Obsidian Stream Hub.",
    "Could not reach the update server.",
    "The update address must use https.",
    "The download stopped. Check the internet and try again.",
    "The download does not match the update note.",
    "Windows did not start the installer (permission refused?).",
    "Updates install only on Windows.",
    "Cancelled.",
)


class UpdateDialog(QDialog):
    _progress = Signal(int, int)
    _finished = Signal(object, str)          # path or None, error text

    def __init__(self, info: updater.UpdateInfo, streaming=lambda: False, parent=None,
                 on_skip=None, launch=updater.run_installer, quit_app=None) -> None:
        super().__init__(parent)
        self.info = info
        self._streaming = streaming
        self._on_skip = on_skip
        self._launch = launch
        self._quit = quit_app or (lambda: QTimer.singleShot(300, QApplication.quit))
        self._cancel = threading.Event()
        self.installed = False
        self.setWindowTitle(T("Update Obsidian Mirror"))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        title = QLabel(T("A new version is ready: {new}").format(new=info.version))
        title.setStyleSheet("font: 700 17px 'Segoe UI';")
        lay.addWidget(title)
        lay.addWidget(QLabel(T("You have {old} · download {mb} MB").format(
            old=__version__, mb=f"{info.size / 1e6:.1f}" if info.size < 10e6 else f"{info.size / 1e6:.0f}"),
            objectName="muted"))
        notes = info.notes_for(current())
        if notes:
            box = QLabel(notes, objectName="notes", wordWrap=True)
            box.setTextFormat(Qt.PlainText)
            lay.addWidget(box)
        if info.required:
            lay.addWidget(QLabel(T("This update is required: the old version no longer works properly."),
                                 objectName="status", wordWrap=True))
        lay.addWidget(QLabel(T("Your settings are kept. The program closes, installs and opens again by "
                               "itself (Windows may ask for permission)."), objectName="muted", wordWrap=True))
        self.bar = QProgressBar(maximum=1000, visible=False)
        lay.addWidget(self.bar)
        self.status = QLabel("", objectName="status", wordWrap=True, visible=False)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.skip = QPushButton(T("Skip this version"), clicked=self._skip, visible=not info.required)
        self.later = QPushButton(T("Later"), clicked=self._later)
        self.go = QPushButton(T("Update now"), objectName="primary", clicked=self.start)
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.later)
        row.addWidget(self.go)
        lay.addLayout(row)
        if not updater.can_install():
            self.go.setEnabled(False)
            self._say(T("Running from source code: update with git pull, or install the new installer."))
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(True)

    def _skip(self) -> None:
        if self._on_skip:
            self._on_skip(self.info.version)
        self.reject()

    def _later(self) -> None:
        self._cancel.set()
        self.reject()

    def start(self) -> None:
        if self._streaming() and QMessageBox.question(
                self, T("Update Obsidian Mirror"),
                T("A phone is mirroring now. Updating stops the picture in OBS for about a minute. Update anyway?")
        ) != QMessageBox.Yes:
            return
        self.go.setEnabled(False)
        self.skip.setEnabled(False)
        self.bar.setVisible(True)
        self._say(T("Downloading…"))
        threading.Thread(target=self._download, name="update-download", daemon=True).start()

    def _download(self) -> None:
        try:
            path = updater.download(self.info, progress=self._progress.emit, cancel=self._cancel)
            self._finished.emit(path, "")
        except updater.UpdateError as exc:
            self._finished.emit(None, str(exc))
        except Exception as exc:
            self._finished.emit(None, f"{type(exc).__name__}: {exc}")

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setValue(int(done * 1000 / max(total, 1)))
        self._say(T("Downloading… {done} / {total} MB").format(done=f"{done / 1e6:.1f}",
                                                               total=f"{total / 1e6:.1f}"))

    def _on_finished(self, path, error: str) -> None:
        if path is None:
            if self._cancel.is_set():
                return
            self._say(T(error))
            self.go.setEnabled(updater.can_install())
            self.go.setText(T("Try again"))
            return
        self._say(T("Checked ✓ Installing — the program will close and open again."))
        try:
            self._launch(path)
        except updater.UpdateError as exc:
            self._say(T(str(exc)))
            self.go.setEnabled(True)
            return
        self.installed = True
        self._quit()


class UpdateController(QObject):
    """Checks at start and every 6 hours; shows the window at a good moment."""
    changed = Signal()                        # an update became known (for the menu)

    def __init__(self, display, url: str | None = None, keys=None, parent=None) -> None:
        super().__init__(parent)
        self.display = display
        self.checker = updater.UpdateChecker(url or display.cfg.update_url or updater.DEFAULT_URL, keys)
        self.checker.available.connect(self._on_available)
        self.checker.up_to_date.connect(self._on_up_to_date)
        self.checker.failed.connect(self._on_failed)
        self.latest: updater.UpdateInfo | None = None
        self.dialog: UpdateDialog | None = None
        self._first = QTimer(self, singleShot=True, interval=updater.FIRST_CHECK_MS, timeout=self.auto_check)
        self._every = QTimer(self, interval=updater.CHECK_EVERY_MS, timeout=self.auto_check)
        self._idle = QTimer(self, singleShot=True, interval=IDLE_MS, timeout=self._offer)

    def start(self) -> None:
        updater.clean_old()                  # the installer that got us here is not needed
        self._first.start()
        self._every.start()

    def auto_check(self) -> None:
        if self.display.cfg.update_check:
            self.checker.check(manual=False)

    def check_now(self) -> None:
        self.checker.check(manual=True)

    def on_stream(self, active: bool) -> None:
        if active:
            self._idle.stop()
        elif self._worth_offering():
            self._idle.start()               # the phone dropped: wait, it may come back

    def _worth_offering(self) -> bool:
        info = self.latest
        return info is not None and (info.required or info.version != self.display.cfg.update_skip)

    def _on_available(self, info, manual: bool) -> None:
        new = self.latest is None or info.version != self.latest.version
        self.latest = info
        if new:
            self.changed.emit()
        if manual:
            self.show()
        elif new and self._worth_offering() and not self.display.streaming:
            self.show()

    def _offer(self) -> None:
        if not self.display.streaming and self._worth_offering():
            self.show()

    def _on_up_to_date(self, manual: bool) -> None:
        if manual:
            QMessageBox.information(self.display.window, T("Update Obsidian Mirror"),
                                    T("You have the latest version ({version}).").format(version=__version__))

    def _on_failed(self, error: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(self.display.window, T("Update Obsidian Mirror"),
                                T("Could not check for updates: {error}").format(error=T(error)))

    def _skip(self, version: str) -> None:
        cfg = self.display.cfg.with_changes(update_skip=version)
        self.display.window._cfg = cfg       # or the window's next save would bring it back
        self.display.on_config(cfg)

    def show(self) -> None:
        if self.latest is None:
            return
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            return
        self.dialog = UpdateDialog(self.latest, lambda: self.display.streaming, self.display.window,
                                   on_skip=self._skip)
        self.dialog.show()
