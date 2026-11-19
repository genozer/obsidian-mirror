# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Dialog: scan a QR with the phone to send its camera (no buttons on it) to the virtual camera."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .i18n import T
from .wifi_dialog import QR_PX, STYLE, qr_pixmap

STEPS_TEXT = (
    "1. Connect the phone to the same Wi‑Fi as this PC\n"
    "2. Scan this code with the phone camera and open the page\n"
    "3. Tap “▶ Start camera” and allow the camera\n"
    "Keep the page open and the screen on while you are live."
)
STATES = {
    "connecting": ("Connecting to the server…", "#c4b5fd"),
    "offline": ("Cannot reach the server. Check the internet on this PC.", "#fbbf24"),
    "waiting": ("Waiting for the phone…", "#c4b5fd"),
    "live": ("Phone camera connected ✓", "#4ade80"),
    "stopped": ("The phone camera is off.", "#a1a1aa"),
}


class PhoneCamDialog(QDialog):
    def __init__(self, url: str, link, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.link = link
        self.setWindowTitle(T("Phone camera (clean picture)"))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        title = QLabel(T("Scan with the phone"), alignment=Qt.AlignCenter)
        title.setStyleSheet("font: 700 17px 'Segoe UI';")
        lay.addWidget(title)
        qr = QLabel(alignment=Qt.AlignCenter)
        qr.setPixmap(qr_pixmap(url, QR_PX))
        lay.addWidget(qr)
        lay.addWidget(QLabel(T(STEPS_TEXT), objectName="muted", wordWrap=True))
        self.status = QLabel(objectName="status", wordWrap=True, alignment=Qt.AlignCenter)
        lay.addWidget(self.status)
        note = QLabel(T("Only the camera picture is sent — no buttons, no status bar. iPhone and Android."),
                      objectName="muted", wordWrap=True, alignment=Qt.AlignCenter)
        note.setStyleSheet("font-size: 11px;")
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QPushButton(T("Copy link"), clicked=self.copy))
        row.addWidget(QPushButton(T("Close"), clicked=self.accept))
        row.addStretch(1)
        lay.addLayout(row)
        if link is not None:
            link.state_changed.connect(self._on_state)
            self._on_state(link.state)

    def _on_state(self, state: str) -> None:
        text, color = STATES.get(state, (state, "#c4b5fd"))
        self.status.setText(T(text))
        self.status.setStyleSheet(f"color: {color}; font-weight: 600;")

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.url)
        self.status.setText(T("Link copied."))
