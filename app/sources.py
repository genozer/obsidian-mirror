# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""One app for both phones: iPhone (AirPlay via UxPlay) or Android (USB via scrcpy).

SourceManager looks like a single receiver to the rest of the app (start, stop, restart,
is_running, update_config, lines and the three signals) and runs only the source the
streamer picked in the menu. Both deliver H.264 to the same local video port.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .android_source import AndroidSource
from .config import AppConfig
from .receiver import UxPlayReceiver


class SourceManager(QObject):
    log_line = Signal(str)
    status_changed = Signal(str)
    client_event = Signal(str)

    def __init__(self, cfg: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.iphone = UxPlayReceiver(cfg, self)
        self.android = AndroidSource(cfg, self)
        for src in (self.iphone, self.android):
            src.log_line.connect(lambda line, s=src: self._forward(s, self.log_line, line))
            src.status_changed.connect(lambda st, s=src: self._forward(s, self.status_changed, st))
            src.client_event.connect(lambda ev, s=src: self._forward(s, self.client_event, ev))

    @property
    def active(self):
        return self.android if self._cfg.source == "android" else self.iphone

    def _forward(self, src, signal, value) -> None:
        if src is self.active:          # ignore the stopped source's last words
            signal.emit(value)

    @property
    def lines(self) -> list[str]:
        return self.active.lines

    def update_config(self, cfg: AppConfig) -> None:
        old = self._cfg
        self._cfg = cfg
        self.iphone.update_config(cfg)
        self.android.update_config(cfg)
        if cfg.source != old.source:
            (self.android if old.source == "android" else self.iphone).stop()
            self.active.start()

    def is_running(self) -> bool:
        return self.active.is_running()

    def start(self) -> None:
        self.active.start()

    def stop(self) -> None:
        self.iphone.stop()
        self.android.stop()

    def restart(self) -> None:
        self.active.restart()
