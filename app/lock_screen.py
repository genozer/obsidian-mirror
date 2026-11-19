# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (English/Thai text; new dark waiting screen
# with a picture and the steps to connect, no clock).
"""Waiting screen shown while there is no picture (phone frame and plain window)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QRadialGradient

from .i18n import T



def _font(px: float, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont("Segoe UI Variable Display")
    f.setPixelSize(max(1, int(px)))
    f.setWeight(weight)
    return f


def paint_wallpaper(p: QPainter, rect: QRectF) -> None:
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#1b1f4b"))
    grad.setColorAt(0.5, QColor("#5b2a86"))
    grad.setColorAt(1.0, QColor("#e2647a"))
    p.fillRect(rect, grad)
    for cx, cy, r, col in ((0.2, 0.75, 0.7, QColor(255, 140, 90, 110)),
                           (0.85, 0.3, 0.6, QColor(70, 120, 255, 110))):
        rg = QRadialGradient(rect.left() + rect.width() * cx, rect.top() + rect.height() * cy,
                             rect.width() * r)
        rg.setColorAt(0, col)
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(rect, rg)


LINK_BADGE = {"usb": "USB", "hotspot": "Hotspot"}


def paint_link_badge(p: QPainter, rect: QRectF, link_kind: str | None) -> None:
    """Плашка слева от Dynamic Island, как индикатор в строке состояния iOS."""
    if not link_kind:
        return
    w = rect.width()
    text = LINK_BADGE.get(link_kind, link_kind)
    p.setFont(_font(w * 0.036, QFont.DemiBold))
    tw = p.fontMetrics().horizontalAdvance(text)
    badge = QRectF(rect.left() + w * 0.08, rect.top() + w * 0.045, tw + w * 0.05, w * 0.06)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#30d158"))
    p.drawRoundedRect(badge, badge.height() / 2, badge.height() / 2)
    p.setPen(QColor("#ffffff"))
    p.drawText(badge, Qt.AlignCenter, text)


# --- Waiting screen (Obsidian Mirror, 2026-11-19): dark grey, a picture of what to do,
# the three taps on the iPhone, and a short hint. No clock: nothing to repaint every
# 15 seconds. Used by the phone frame and by the plain window.
TITLES = {
    "running": "Waiting for the iPhone",
    "connecting": "Connecting…",
    "preview_off": "Mirroring ✓",
    "error": "The receiver stopped",
    "missing": "UxPlay is not installed",
    "stopped": "Receiver is off",
}
LINK_TITLES = {"usb": "Connected by cable ✓", "hotspot": "Through the iPhone hotspot ✓"}
SUBTITLES = {
    "preview_off": "Picture hidden to save the PC.\nThe OBS link keeps working.",
    "error": "Right-click → “Restart receiver”",
    "missing": "Run setup\\install.ps1",
    "stopped": "Right-click → “Restart receiver”",
}
STEPS = (
    "Open Control Center on the iPhone\n(swipe down from the top-right corner)",
    "Tap “Screen Mirroring”",
    "Choose “{name}”",
)
HINT = "Right-click for settings"
ICONS = {"running": "waiting.svg", "connecting": "waiting.svg", "preview_off": "mirroring.svg",
         "android_waiting": "android.svg", "android_unauthorized": "android.svg"}

# Android (USB, scrcpy): one-time phone setup, then just plug in.
TITLES.update({
    "android_waiting": "Waiting for the Android phone (beta)",
    "android_unauthorized": "Allow USB debugging on the phone",
    "android_no_adb": "adb is missing",
})
SUBTITLES.update({
    "android_unauthorized": "Tap “Allow” on the phone screen\n(tick “Always allow from this computer”)",
    "android_no_adb": "Run setup\\get_scrcpy.ps1",
})
ANDROID_STEPS = (
    "Turn on Developer options\n(Settings → About phone → tap Build number 7 times)",
    "Turn on USB debugging\n(Settings → System → Developer options)",
    "Connect the USB cable and tap “Allow” on the phone",
)
STEP_SETS = {"running": STEPS, "android_waiting": ANDROID_STEPS}
OTHER_PHONE = {
    "running": "Using an Android phone?\nRight-click → Phone → Android (USB cable or Wi‑Fi) · beta",
    "android_waiting": "No cable? (Android 11+)\nRight-click → Phone → Connect Android over Wi‑Fi (QR code)",
}

BG_TOP = QColor("#2c2c31")
BG_BOTTOM = QColor("#1d1d21")
TEXT = QColor("#f4f4f5")
MUTED = QColor("#a1a1aa")
ACCENT = QColor("#8b5cf6")

_svg_cache: dict[str, object] = {}


def _svg(name: str):
    """QSvgRenderer for assets/<name>, loaded once."""
    if name not in _svg_cache:
        from PySide6.QtSvg import QSvgRenderer
        from .paths import RESOURCE_DIR
        _svg_cache[name] = QSvgRenderer(str(RESOURCE_DIR / "assets" / name))
    return _svg_cache[name]


def _text(p: QPainter, rect: QRectF, text: str, px: float, color: QColor,
          weight: QFont.Weight = QFont.Normal, flags=Qt.AlignHCenter | Qt.AlignTop) -> float:
    """Draws wrapped text; returns the height it used."""
    p.setFont(_font(px, weight))
    p.setPen(color)
    used = p.boundingRect(rect, flags | Qt.TextWordWrap, text)
    p.drawText(rect, flags | Qt.TextWordWrap, text)
    return used.height()


def paint_lock_screen(p: QPainter, rect: QRectF, status: str, device_name: str,
                      link_kind: str | None = None) -> None:
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, BG_TOP)
    grad.setColorAt(1.0, BG_BOTTOM)
    p.fillRect(rect, grad)
    paint_link_badge(p, rect, link_kind)
    w, h = rect.width(), rect.height()
    unit = min(w, h * 0.56)                     # keeps proportions in wide plain windows
    col = QRectF(rect.center().x() - unit / 2, rect.top(), unit, h)
    steps = STEP_SETS.get(status)
    waiting = steps is not None

    # Picture (the block of picture + title + steps sits a little above the middle).
    icon = min(unit * 0.5, h * 0.24)
    block = icon + unit * (0.9 if waiting else 0.35)
    top = rect.top() + max(h * 0.08, (h - block) * 0.48)
    svg = _svg(ICONS.get(status, "alert.svg"))
    svg.render(p, QRectF(rect.center().x() - icon / 2, top, icon, icon))
    y = top + icon + unit * 0.05

    # Title.
    title = T(LINK_TITLES[link_kind]) if (status == "running" and link_kind in LINK_TITLES) else \
        T(TITLES.get(status, TITLES["running"]))
    y += _text(p, QRectF(col.left(), y, unit, h), title, unit * 0.072, TEXT, QFont.Bold)
    y += unit * 0.05

    if waiting:
        # The three taps on the iPhone.
        num = unit * 0.075
        text_left = col.left() + unit * 0.08 + num + unit * 0.04
        text_w = col.right() - unit * 0.06 - text_left
        for i, step in enumerate(steps, 1):
            circle = QRectF(col.left() + unit * 0.08, y, num, num)
            p.setPen(Qt.NoPen)
            p.setBrush(ACCENT)
            p.drawEllipse(circle)
            _text(p, circle, str(i), num * 0.6, QColor("#ffffff"), QFont.Bold, Qt.AlignCenter)
            first, _, rest = T(step).format(name=device_name).partition("\n")
            used = _text(p, QRectF(text_left, y + num * 0.02, text_w, h), first, unit * 0.05, TEXT,
                         QFont.DemiBold if i == 3 else QFont.Medium, Qt.AlignLeft | Qt.AlignTop)
            if rest:
                used += _text(p, QRectF(text_left, y + num * 0.02 + used, text_w, h), rest,
                              unit * 0.04, MUTED, QFont.Normal, Qt.AlignLeft | Qt.AlignTop)
            y += max(num, used) + unit * 0.045
        # How to switch to the other kind of phone (a soft card under the steps).
        other = OTHER_PHONE.get(status)
        if other:
            y += unit * 0.03
            card = QRectF(col.left() + unit * 0.06, y, unit * 0.88, unit * 0.19)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(card, unit * 0.035, unit * 0.035)
            ask, _, how = T(other).partition("\n")
            inner = card.adjusted(unit * 0.04, unit * 0.03, -unit * 0.04, 0)
            used = _text(p, inner, ask, unit * 0.044, TEXT, QFont.DemiBold)
            _text(p, inner.adjusted(0, used + unit * 0.008, 0, 0), how, unit * 0.04, MUTED)
    elif status in SUBTITLES:
        _text(p, QRectF(col.left() + unit * 0.06, y, unit * 0.88, h), T(SUBTITLES[status]),
              unit * 0.048, MUTED)

    # Hint at the bottom.
    _text(p, QRectF(col.left(), rect.bottom() - unit * 0.13, unit, unit * 0.1), T(HINT),
          unit * 0.042, MUTED, QFont.Normal, Qt.AlignHCenter | Qt.AlignVCenter)
