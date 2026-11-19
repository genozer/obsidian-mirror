# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Fold (minimize) a window to the taskbar so that it really leaves the screen.

Found while testing on 2026-11-19: the phone window is a frameless *layered* window
(WS_EX_LAYERED). If it was hidden at some point and is then minimized, Windows marks it
minimized (IsIconic) but leaves it where it was, frozen on screen. Restoring and
minimizing again moves it off screen properly, so this checks and retries.
"""
from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

CHECK_MS = 250
MINIMIZED_POS = -32000            # where Windows parks a properly minimized window
RETRIES = 2


def is_off_screen(widget: QWidget) -> bool:
    """True when the window is really folded (not just flagged as minimized)."""
    if sys.platform != "win32":
        return widget.isMinimized()
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = int(widget.winId())
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return widget.isMinimized()
    return bool(user32.IsIconic(hwnd)) and rect.left <= MINIMIZED_POS + 1000


def fold(widget: QWidget, retries: int = RETRIES) -> None:
    widget.showMinimized()
    if sys.platform != "win32":
        return

    def check(left: int = retries) -> None:
        if not widget.isMinimized():
            return                # restored by the user (or the app) meanwhile: leave it
        if is_off_screen(widget):
            return
        if left <= 0:
            log.warning("window could not be folded off screen")
            return
        widget.showNormal()       # the stuck state clears only after a real restore
        widget.showMinimized()
        QTimer.singleShot(CHECK_MS, lambda: check(left - 1))

    QTimer.singleShot(CHECK_MS, check)
