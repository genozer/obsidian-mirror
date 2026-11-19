# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
"""Тесты обычного окна: геометрия картинки, инструменты, переключение режимов."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage

from app.config import AppConfig
from app.image_ops import oriented_image, oriented_size, target_rect
from app.plain_window import PlainWindow, window_size_for

AREA = QRectF(0, 0, 1000, 500)


def test_oriented_size_swaps_on_odd_rotation():
    assert oriented_size(QSizeF(9, 19), 1) == QSizeF(19, 9)
    assert oriented_size(QSizeF(9, 19), 2) == QSizeF(9, 19)


@pytest.mark.parametrize("mode,expected", [
    ("fit", QRectF(450, 0, 100, 500)),          # пропорции сохранены, поля по бокам
    ("stretch", AREA),                           # на всё окно
    ("fill", QRectF(0, -2250, 1000, 5000)),      # закрывает всё, лишнее обрезается
])
def test_target_rect_modes(mode, expected):
    assert target_rect(QSizeF(100, 500), AREA, mode) == expected


def test_oriented_image_rotates_and_mirrors():
    img = QImage(2, 1, QImage.Format_RGB32)
    img.setPixelColor(0, 0, QColor("red"))
    img.setPixelColor(1, 0, QColor("blue"))
    rotated = oriented_image(img, 1, False)          # 90° по часовой: красный сверху
    assert (rotated.width(), rotated.height()) == (1, 2)
    assert rotated.pixelColor(0, 0) == QColor("red")
    mirrored = oriented_image(img, 0, True)
    assert mirrored.pixelColor(0, 0) == QColor("blue")


def test_window_size_follows_aspect_and_screen():
    size = window_size_for(QSizeF(9, 19.5), 780, 52, QSizeF(1900, 1000))
    assert size.height() == 780 and size.width() == round(780 * 9 / 19.5 + 52)
    wide = window_size_for(QSizeF(1920, 886), 900, 52, QSizeF(1200, 1000))
    assert wide.width() == 1200


@pytest.fixture()
def win():
    w = PlainWindow(AppConfig(view_mode="window"), lambda: [])
    changes = []
    w.config_changed.connect(changes.append)
    w.changes = changes
    yield w
    w.close()


def test_rotate_cycles_and_persists(win):
    win.rotate(1)
    win.rotate(1)
    win.rotate(-1)
    assert win.changes[-1].rotation == 1


def test_mirror_button_and_shortcut_state(win):
    win.btn_mirror.toggle()
    assert win.changes[-1].mirrored is True
    win.reset_transform()
    assert win.changes[-1].mirrored is False and win.changes[-1].rotation == 0


def test_fit_mode_changes_icon(win):
    win.set_fit_mode("stretch")
    assert win.changes[-1].fit_mode == "stretch"
    assert win.btn_fit.text() == ""


def test_screenshot_is_rotated_like_display(win):
    frame = QImage(40, 80, QImage.Format_RGB32)
    frame.fill(Qt.white)
    win.show_frame(frame)
    win.rotate(1)
    shot = win.screenshot_image
    assert (shot.width(), shot.height()) == (80, 40)


def test_controller_switch_keeps_frame_and_link(monkeypatch):
    from app.__main__ import DisplayController
    from app.usb_link import DirectLink
    monkeypatch.setattr("app.__main__.save_config", lambda cfg: None)   # не трогаем настоящий config.json

    class FakeReceiver:
        lines: list[str] = []
        def update_config(self, cfg): self.cfg = cfg
        def restart(self): pass
        def is_running(self): return True

    class FakeServer:
        target_box = (0, 0, False)
        use_gpu = True
        preview_enabled = True
        repair = None
        def full_image(self): return None

    ctl = DisplayController(AppConfig(view_mode="phone"), FakeReceiver(), FakeServer(), None)
    frame = QImage(40, 80, QImage.Format_RGB32)
    frame.fill(Qt.white)
    ctl.on_frame(frame)
    ctl.set_link(DirectLink("usb", "Ethernet 4", "172.20.10.2"))
    ctl.switch("window")
    assert isinstance(ctl.window, PlainWindow)
    assert ctl.cfg.view_mode == "window"
    assert ctl.window.is_streaming and ctl.window._link.kind == "usb"
    ctl.switch("phone")
    assert ctl.window.is_streaming
    # Language switch rebuilds the window in the new language and keeps the picture.
    ctl.on_config(ctl.cfg.with_changes(language="th"))
    assert ctl.window.is_streaming and ctl.cfg.language == "th"
    menu_texts = [a.text() for a in ctl.window._build_menu().actions()]
    assert "ภาษา / Language" in menu_texts and "เริ่มตัวรับภาพใหม่" in menu_texts
    # Preview "never": the window shows the note instead of the picture.
    ctl.on_config(ctl.cfg.with_changes(preview_mode="off"))
    ctl.on_stream(True)
    assert ctl.status == "preview_off" and not ctl.window.is_streaming
    from app.i18n import set_language
    set_language("en")
    ctl.window.close()


def test_auto_preview_shows_a_minute_hides_and_pops_up_on_disconnect(monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from app.__main__ import DisplayController
    monkeypatch.setattr("app.__main__.save_config", lambda cfg: None)
    monkeypatch.setattr("app.__main__.PEEK_MS", 80)            # 1 minute → 80 ms for the test

    class FakeReceiver:
        lines: list[str] = []
        def update_config(self, cfg): self.cfg = cfg
        def restart(self): pass
        def is_running(self): return True

    class FakeServer:
        target_box = (0, 0, False)
        use_gpu = True
        preview_enabled = True
        repair = None
        def full_image(self): return None

    server = FakeServer()
    ctl = DisplayController(AppConfig(view_mode="phone"), FakeReceiver(), server, None)
    assert AppConfig().preview_mode == "auto"
    ctl.window.show()
    frame = QImage(40, 80, QImage.Format_RGB32)
    frame.fill(Qt.white)

    def wait(ms):
        end = time.time() + ms / 1000
        while time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    # Phone connects: picture shown...
    ctl.on_stream(True)
    ctl.on_frame(frame)
    assert server.preview_enabled and ctl.window.is_streaming
    # ...for "a minute", then hidden and the window minimized; no more frame work.
    wait(300)
    assert not server.preview_enabled and ctl.status == "preview_off"
    assert ctl.window.isMinimized()
    ctl.on_frame(frame)
    assert not ctl.window.is_streaming
    # Phone drops: the window comes back up, ready to show the next connection.
    ctl.on_stream(False)
    assert not ctl.window.isMinimized() and server.preview_enabled
    assert ctl.status == "running"
    # Reconnects: shown again for a minute, then hidden again.
    ctl.on_stream(True)
    ctl.on_frame(frame)
    assert ctl.window.is_streaming
    wait(300)
    assert ctl.window.isMinimized() and not server.preview_enabled
    # "Show preview for 1 minute" from the menu brings it back for another minute.
    ctl.peek_preview()
    assert server.preview_enabled and not ctl.window.isMinimized()
    ctl.window.close()
