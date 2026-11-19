# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""The window shown before anything else until the streamer signs in (app/account.py)."""
from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import account as acc
from .i18n import T
from .paths import ICON_PATH

SHOW_AFTER_MS = 700     # a quick "still signed in" check never flashes a window


class _Bridge(QObject):
    checked = Signal(str)
    signed_in = Signal()
    failed = Signal(str)


class LoginDialog(QDialog):
    def __init__(self, account: acc.Account, opener=webbrowser.open) -> None:
        super().__init__()
        self.account, self.opener = account, opener
        self.waiter: acc.LoginWaiter | None = None
        self.bridge = _Bridge()
        self.bridge.checked.connect(self._on_checked)
        self.bridge.signed_in.connect(self.accept)
        self.bridge.failed.connect(self._on_failed)

        self.setWindowTitle("Obsidian Mirror")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        if ICON_PATH.is_file():
            icon = QLabel(alignment=Qt.AlignCenter)
            icon.setPixmap(QPixmap(str(ICON_PATH)).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lay.addWidget(icon)
        title = QLabel(T("Sign in to Obsidian Mirror"), alignment=Qt.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:700")
        lay.addWidget(title)
        info = QLabel(T("Use your Obsidian Hub account (free on every plan). The browser opens "
                        "for the sign-in; Google accounts work too."), alignment=Qt.AlignCenter)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.status = QLabel("", alignment=Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8a93a6")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.sign_in = QPushButton(T("Sign in with the browser"))
        self.sign_in.setDefault(True)
        self.sign_in.setMinimumHeight(36)
        self.sign_in.clicked.connect(self.start_login)
        quit_btn = QPushButton(T("Quit"))
        quit_btn.clicked.connect(self.reject)
        row.addWidget(self.sign_in, 1)
        row.addWidget(quit_btn)
        lay.addLayout(row)

    # 1. at start: is the saved sign-in still good?
    def run(self) -> bool:
        """True = go on to the app. Shows the window only when needed."""
        self._result: str | None = None
        self.sign_in.setEnabled(False)
        self.status.setText(T("Checking your account…"))
        threading.Thread(target=lambda: self.bridge.checked.emit(self.account.check()),
                         name="account-check", daemon=True).start()
        loop = QEventLoop()
        self.bridge.checked.connect(loop.quit)
        QTimer.singleShot(SHOW_AFTER_MS, loop.quit)
        loop.exec()
        if self._result == acc.OK:
            return True
        return self.exec() == QDialog.Accepted

    def _on_checked(self, result: str) -> None:
        self._result = result
        if result == acc.OK:
            if self.isVisible():
                self.accept()
            return
        self.sign_in.setEnabled(result != acc.OFF)
        self.status.setText({
            acc.LOGIN: "",
            acc.OFF: T("Phone Cast is switched off for this account. Contact us through "
                       "\"Report a problem\" in the dashboard."),
            acc.OFFLINE: T("Could not reach Obsidian Hub for a while. Connect to the internet, then sign in."),
        }.get(result, ""))

    # 2. the browser sign-in
    def start_login(self) -> None:
        if self.waiter is not None:
            self.waiter.close()
        url, self.waiter, verifier = self.account.begin_login()
        waiter = self.waiter
        self.sign_in.setText(T("Open the browser again"))
        self.status.setText(T("Finish signing in in the browser, then come back here."))
        self.opener(url)

        def wait() -> None:
            code = waiter.wait()
            if waiter is not self.waiter:      # a newer attempt replaced this one
                return
            waiter.close()
            if not code:
                self.bridge.failed.emit(T("Sign-in took too long. Please try again."))
                return
            try:
                self.account.finish_login(code, verifier)
            except acc.AccountError as exc:
                self.bridge.failed.emit(str(exc))
                return
            self.bridge.signed_in.emit()

        threading.Thread(target=wait, name="login-wait", daemon=True).start()

    def _on_failed(self, text: str) -> None:
        self.sign_in.setText(T("Sign in with the browser"))
        self.sign_in.setEnabled(True)
        self.status.setText(text)

    def done(self, r: int) -> None:  # noqa: D401 - Qt override
        if self.waiter is not None:
            self.waiter.close()
        super().done(r)
