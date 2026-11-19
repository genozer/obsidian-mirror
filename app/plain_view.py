# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (English/Thai text; reports its drawing size;
# uses the shared waiting screen).
"""Видеообласть обычного окна: кадр с поворотом/зеркалом/режимом вписывания или заглушка."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from .image_ops import oriented_image, oriented_size, paint_oriented
from .lock_screen import paint_lock_screen

BACKGROUND = QColor("#0e0d12")
CARD = QColor(255, 255, 255, 18)
TEXT = QColor("#e9e4f5")
MUTED = QColor("#9b91b3")
BADGE = QColor("#30d158")
ICON_FONT = "Segoe Fluent Icons"
PHONE_GLYPH = ""
DEFAULT_ASPECT = QSizeF(9, 19.5)       # портрет iPhone, пока нет кадров


class PlainView(QWidget):
    double_clicked = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, device_name: str, fit_mode: str, rotation: int, mirrored: bool, parent=None) -> None:
        super().__init__(parent)
        self._device_name = device_name
        self._fit_mode = fit_mode
        self._rotation = rotation % 4
        self._mirrored = mirrored
        self._image: QImage | None = None
        self._streaming = False
        self._status = "running"
        self._link_kind: str | None = None
        self.on_target = None             # callable(box) — set by the app (decoder size)
        self._last_box = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(160, 160)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    # --- состояние ------------------------------------------------------------
    @property
    def current_image(self) -> QImage | None:
        return self._image if self._streaming else None

    def displayed_image(self) -> QImage | None:
        img = self.current_image
        return oriented_image(img, self._rotation, self._mirrored) if img is not None else None

    def content_aspect(self) -> QSizeF:
        """Пропорции того, что сейчас видно (с учётом поворота)."""
        base = QSizeF(self._image.size()) if self.current_image is not None else DEFAULT_ASPECT
        return oriented_size(base, self._rotation)

    def set_transform(self, fit_mode: str, rotation: int, mirrored: bool) -> None:
        self._fit_mode, self._rotation, self._mirrored = fit_mode, rotation % 4, mirrored
        self.update()

    def set_device_name(self, name: str) -> None:
        self._device_name = name
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def set_link(self, kind: str | None) -> None:
        self._link_kind = kind
        self.update()

    def set_streaming(self, active: bool) -> None:
        self._streaming = active
        if not active:
            self._image = None
        self.update()

    def show_frame(self, image: QImage) -> None:
        self._image = image
        self._streaming = True
        self.update()

    # --- события ------------------------------------------------------------
    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def contextMenuEvent(self, e) -> None:
        self.menu_requested.emit(e.globalPos())

    # --- отрисовка ----------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        area = QRectF(self.rect())
        p.fillRect(area, BACKGROUND)
        self._report_target(area)
        if self.current_image is not None:
            paint_oriented(p, self._image, area, self._fit_mode, self._rotation, self._mirrored)
        else:
            self._paint_placeholder(p, area)
        p.end()

    def _report_target(self, area: QRectF) -> None:
        """Tells the decoder how big the picture is drawn, so it converts frames at that
        size instead of full resolution (much less work per frame)."""
        if self.on_target is None:
            return
        dpr = self.devicePixelRatioF()
        w, h = int(area.width() * dpr), int(area.height() * dpr)
        if self._rotation % 2:
            w, h = h, w
        box = (w, h, self._fit_mode == "fill")
        if box != self._last_box:
            self._last_box = box
            self.on_target(box)

    def _paint_placeholder(self, p: QPainter, area: QRectF) -> None:
        # Same waiting screen as the phone frame (dark grey, picture, steps, hint).
        paint_lock_screen(p, area, self._status, self._device_name, self._link_kind)
