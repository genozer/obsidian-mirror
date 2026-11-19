# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (renamed; the author's logo is not used —
# it is not covered by the GPL — and the original author is credited in text instead).
"""About window."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from . import __app_name__, __author_en__, __brand__, __fork_by__, __upstream_version__, __url__, __version__
from .i18n import T


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(T("About"))
        self.setStyleSheet("QDialog { background: #120d1f; } QLabel { color: #e9e4f5; }"
                           "QPushButton { background: #7c3aed; color: white; border: none;"
                           " border-radius: 8px; padding: 6px 18px; font-weight: 600; }"
                           "QPushButton:hover { background: #8b5cf6; }")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(10)

        text = QLabel(
            f"<div style='text-align:center'>"
            f"<p style='font-size:18px; font-weight:600'>{__app_name__} {__version__}</p>"
            f"<p>{escape(T('iPhone screen and sound on Windows — over Wi‑Fi or cable, with an OBS Browser Source link.'))}</p>"
            f"<p>{escape(T('Based on'))} <b>iPhone Mirror {__upstream_version__}</b><br>"
            f"© 2026 {__author_en__} (Сорокин Иван, {__brand__})<br>"
            f"<a style='color:#a78bfa' href='{__url__}'>{__url__}</a></p>"
            f"<p>{escape(T('Changes in this version'))}: {escape(T('Thai/English menus, graphics-card decoding, OBS Browser Source.'))}"
            f"<br>© 2026 {__fork_by__}</p>"
            f"<p style='color:#9b91b3; font-size:11px'>{T('License GPL-3.0-or-later. Uses UxPlay, GStreamer, FFmpeg, Qt.<br>AirPlay and iPhone are trademarks of Apple Inc. Not affiliated with Apple.')}</p></div>",
            alignment=Qt.AlignCenter, openExternalLinks=True, wordWrap=True)
        lay.addWidget(text)

        ok = QPushButton(T("Close"), clicked=self.accept)
        lay.addWidget(ok, alignment=Qt.AlignCenter)
