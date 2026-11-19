# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (reports its drawing size for decoding;
# the phone is drawn once into cached pictures while mirroring).
"""Виджет, рисующий iPhone с транслируемым экраном внутри."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from . import phone_skin as skin
from .lock_screen import paint_lock_screen



def fit_rect(image_size: QSize, target: QRectF) -> QRectF:
    """Вписывает изображение в target с сохранением пропорций (по центру)."""
    if image_size.isEmpty():
        return QRectF(target)
    k = min(target.width() / image_size.width(), target.height() / image_size.height())
    w, h = image_size.width() * k, image_size.height() * k
    return QRectF(target.center().x() - w / 2, target.center().y() - h / 2, w, h)


class PhoneView(QWidget):
    def __init__(self, scale: float, color: str, device_name: str, parent=None) -> None:
        super().__init__(parent)
        self._scale = scale
        self._color = color
        self._device_name = device_name
        self._image: QImage | None = None
        self._status = "running"
        self._streaming = False
        self._link_kind: str | None = None
        self.on_target = None             # callable(box) — set by the app (decoder size)
        self._last_box = None
        self._layer_key = None
        self._layer_cache = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)       # курсор-стрелки над краями корпуса
        self._apply_size()

    # --- публичное API -----------------------------------------------------
    @property
    def landscape(self) -> bool:
        img = self._image
        return self._streaming and img is not None and img.width() > img.height()

    @property
    def current_image(self) -> QImage | None:
        return self._image if self._streaming else None

    @property
    def scale(self) -> float:
        return self._scale

    def body_rect(self) -> QRectF:
        """Корпус телефона в координатах виджета (с учётом поворота)."""
        layout = skin.PhoneLayout.create(self._scale)
        return self._transform(layout).mapRect(layout.body)

    def set_scale(self, scale: float) -> None:
        self._scale = scale
        self._apply_size()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def set_device_name(self, name: str) -> None:
        self._device_name = name
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def set_link(self, link_kind: str | None) -> None:
        self._link_kind = link_kind
        self.update()

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        if not streaming:
            self._image = None
        self._apply_size()

    def show_frame(self, image: QImage) -> None:
        was_landscape = self.landscape
        self._image = image
        self._streaming = True
        if self.landscape != was_landscape:
            self._apply_size()
            return
        if self._layer_cache is not None and self._layer_key and self._layer_key[2] == self.landscape:
            self.update(self._layer_cache[2].toAlignedRect())   # only the screen changes
        else:
            self.update()

    # --- размер/повороты ---------------------------------------------------
    def _apply_size(self) -> None:
        canvas = skin.PhoneLayout.create(self._scale).canvas
        w, h = round(canvas.width()), round(canvas.height())
        self.setFixedSize(QSize(h, w) if self.landscape else QSize(w, h))
        self.update()

    def _transform(self, layout: skin.PhoneLayout) -> QTransform:
        if not self.landscape:
            return QTransform()
        # Поворот на -90°: верх телефона (Dynamic Island) уходит влево.
        return QTransform().translate(0, layout.canvas.width()).rotate(-90)

    # --- отрисовка ---------------------------------------------------------
    def _layers(self, layout: skin.PhoneLayout, t: QTransform) -> tuple[QPixmap, QPixmap, QRectF]:
        """The phone drawn once into two pictures: what lies under the video (shadow,
        buttons, body) and what lies over it (rounded screen corners, island, glare).
        Rebuilt only when size, colour or orientation change — not 60 times a second."""
        dpr = self.devicePixelRatioF()
        key = (self._scale, self._color, self.landscape, dpr, self.width(), self.height())
        if self._layer_key != key:
            s = self._scale
            under = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
            under.setDevicePixelRatio(dpr)
            under.fill(Qt.transparent)
            p = QPainter(under)
            p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            p.setTransform(t)
            skin.paint_shadow(p, layout, s)
            skin.paint_buttons(p, layout, s, self._color)
            skin.paint_body(p, layout, s, self._color)
            p.end()
            over = QPixmap(under.size())
            over.setDevicePixelRatio(dpr)
            over.fill(Qt.transparent)
            p = QPainter(over)
            p.setRenderHints(QPainter.Antialiasing)
            p.setTransform(t)
            corners = QPainterPath()
            corners.addRect(layout.screen)
            corners = corners.subtracted(skin.screen_path(layout, s))
            p.fillPath(corners, QColor("#050505"))      # same black as the glass around the screen
            skin.paint_island(p, layout, s, active=True)
            skin.paint_glass_glare(p, layout, s)
            p.end()
            self._layer_cache = (under, over, t.mapRect(layout.screen))
            self._layer_key = key
        return self._layer_cache

    def paintEvent(self, _event) -> None:
        layout = skin.PhoneLayout.create(self._scale)
        s = self._scale
        t = self._transform(layout)
        if self._streaming and self._image is not None:
            # Fast path while mirroring: two cached pictures + the frame (already converted
            # at this size by the decoder thread, so no scaling here).
            under, over, screen = self._layers(layout, t)
            p = QPainter(self)
            p.drawPixmap(0, 0, under)
            p.fillRect(screen, QColor("#000"))
            self._report_box(screen)
            p.drawImage(fit_rect(self._image.size(), screen), self._image)
            p.drawPixmap(0, 0, over)
            p.end()
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.setTransform(t)
        skin.paint_shadow(p, layout, s)
        skin.paint_buttons(p, layout, s, self._color)
        skin.paint_body(p, layout, s, self._color)
        p.save()
        p.setClipPath(skin.screen_path(layout, s))
        if self._streaming and self._image is not None:
            self._paint_video(p, layout, t)
        else:
            paint_lock_screen(p, layout.screen, self._status, self._device_name, self._link_kind)
        p.restore()
        p.setTransform(t)
        skin.paint_island(p, layout, s, active=self._streaming)
        skin.paint_glass_glare(p, layout, s)
        p.end()

    def _report_box(self, target: QRectF) -> None:
        """Tell the decoder the drawn size: it converts frames at that size, not full size."""
        if self.on_target is None:
            return
        dpr = self.devicePixelRatioF()
        box = (int(target.width() * dpr), int(target.height() * dpr), False)
        if box != self._last_box:
            self._last_box = box
            self.on_target(box)

    def _paint_video(self, p: QPainter, layout: skin.PhoneLayout, t: QTransform) -> None:
        p.fillRect(layout.screen, QColor("#000"))
        # Видео рисуем в экранных координатах виджета (без поворота).
        target = t.mapRect(layout.screen)
        self._report_box(target)
        p.setTransform(QTransform())
        p.setClipPath(t.map(skin.screen_path(layout, self._scale)))
        p.drawImage(fit_rect(self._image.size(), target), self._image)
