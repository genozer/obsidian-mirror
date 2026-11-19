# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Dialog: pair an Android phone over Wi‑Fi by scanning a QR code (android_wifi.py)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from .android_wifi import WifiPairing
from .i18n import T

QR_PX = 260
STYLE = ("QDialog { background: #1f1f23; } QLabel { color: #f4f4f5; }"
         "QLabel#muted { color: #a1a1aa; } QLabel#status { color: #c4b5fd; font-weight: 600; }"
         "QPushButton { background: #3f3f46; color: white; border: none; border-radius: 8px;"
         " padding: 6px 18px; } QPushButton:hover { background: #52525b; }")
STEPS_TEXT = (
    "1. Connect the phone to the same Wi‑Fi as this PC\n"
    "2. Settings → Developer options → Wireless debugging → On\n"
    "3. Tap “Pair device with QR code” and scan this code"
)
STATUS = {
    "starting": "Starting…",
    "waiting": "Waiting for the phone to scan…",
    "pairing": "Pairing…",
    "connecting": "Paired ✓ Connecting…",
    "done": "Connected ✓ From now on it connects by itself when Wireless debugging is on.",
}
FAILED = {
    "mdns": "This PC cannot search the network for phones (adb mDNS is off).",
    "timeout": "No phone scanned the code in 3 minutes. Close and try again.",
}


def qr_pixmap(text: str, size: int) -> QPixmap:
    """QR code drawn with QPainter (sharp at any size). Needs the `segno` package."""
    import segno
    matrix = [list(row) for row in segno.make(text, error="m", micro=False).matrix_iter(border=2)]
    n = len(matrix)
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    cell = size / n
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(QRectF(x * cell, y * cell, cell + 0.5, cell + 0.5))
    p.end()
    return QPixmap.fromImage(img)


class WifiPairDialog(QDialog):
    def __init__(self, adb: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(T("Connect Android over Wi‑Fi"))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(420)
        self.pairing = WifiPairing(adb, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        title = QLabel(T("Scan with the Android phone"), alignment=Qt.AlignCenter)
        title.setStyleSheet("font: 700 17px 'Segoe UI';")
        lay.addWidget(title)
        self.qr = QLabel(alignment=Qt.AlignCenter)
        self.qr.setPixmap(qr_pixmap(self.pairing.payload, QR_PX))
        lay.addWidget(self.qr)
        steps = QLabel(T(STEPS_TEXT), objectName="muted", wordWrap=True)
        lay.addWidget(steps)
        self.status = QLabel(T(STATUS["starting"]), objectName="status", wordWrap=True,
                             alignment=Qt.AlignCenter)
        lay.addWidget(self.status)
        note = QLabel(T("Android 11 or newer. Older phones: use the USB cable."), objectName="muted",
                      wordWrap=True, alignment=Qt.AlignCenter)
        note.setStyleSheet("font-size: 11px;")
        lay.addWidget(note)
        close = QPushButton(T("Close"), clicked=self.reject)
        lay.addWidget(close, alignment=Qt.AlignCenter)
        self.pairing.step.connect(self._on_step)
        self.pairing.start()

    def _on_step(self, step: str, detail: str) -> None:
        if step == "failed":
            msg = T(FAILED[detail]) if detail in FAILED else T("Pairing failed: {err}").format(err=detail)
            self.status.setText(msg)
            self.status.setStyleSheet("color: #fbbf24;")
            return
        self.status.setText(T(STATUS.get(step, step)))
        if step == "done":
            self.status.setStyleSheet("color: #4ade80;")
            self.qr.setEnabled(False)
            QTimer.singleShot(2500, self.accept)

    def done(self, result: int) -> None:  # noqa: A003 - Qt API
        self.pairing.cancel()
        super().done(result)
