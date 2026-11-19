# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (renamed; language switch, GPU decoding,
# preview on/off, the OBS Browser Source, updates and the virtual camera wired in).
"""Entry point: python -m app"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __app_name__, __fork_by__, __version__
from .config import AppConfig, load_config, save_config
from .i18n import T, set_language
from .main_window import MirrorWindow
from .paths import ICON_PATH
from .plain_window import PlainWindow
from .sources import SourceManager
from .single_instance import InstanceServer, notify_running_instance
from .usb_link import LinkMonitor
from .video_stream import VideoServer
from .repair import Repairer
from .update_dialog import UpdateController
from .web_source import WebSource
from .win_fold import fold

WINDOW_CLASSES = {"phone": MirrorWindow, "window": PlainWindow}
PEEK_MS = 60_000           # auto preview: how long the picture stays after connecting


class DisplayController:
    """Owns the active window (phone or plain) and swaps them without breaking the stream."""

    def __init__(self, cfg: AppConfig, receiver: SourceManager, server: VideoServer,
                 web: WebSource | None) -> None:
        self.cfg = cfg
        self.receiver = receiver
        self.server = server
        self.web = web
        self.status = "running"
        self.link = None
        self.last_image = None
        self.streaming = False
        self.updates = None          # UpdateController, set by main() before the first window
        self.account = None          # app/account.py Account, set by main()
        self.camera = None           # VirtualCamera while it is on
        self.phone_link = None       # PhoneCamLink when the camera takes the phone_cam page
        self.preview_on = cfg.preview_mode != "off"
        server.preview_enabled = self.preview_on
        # Preview mode "auto": after the phone connects the picture is shown for a minute
        # (to check it works), then hidden and the window minimized; the OBS link keeps
        # running. If the phone disconnects the window comes back up.
        self._peek = QTimer(singleShot=True, interval=PEEK_MS, timeout=self._end_peek)
        self.window = self._make(cfg.view_mode)

    def _make(self, mode: str):
        win = WINDOW_CLASSES[mode](self.cfg, lambda: self.receiver.lines)
        win._web = self.web
        win._full_image = self.server.full_image
        win._peek_preview = self.peek_preview
        win._updates = self.updates
        win._show_phone_cam = self.show_phone_cam
        win._phone_state = self.phone_state
        win._account = self.account
        win.view.on_target = self._set_target
        win.config_changed.connect(self.on_config)
        win.restart_requested.connect(self.receiver.restart)
        win.mode_requested.connect(self.switch)
        return win

    def _set_target(self, box) -> None:
        self.server.target_box = box

    def on_config(self, cfg: AppConfig) -> None:
        old = self.cfg
        self.cfg = cfg
        self.receiver.update_config(cfg)
        self.server.use_gpu = cfg.use_gpu
        if self.server.repair is not None:
            self.server.repair.fps = cfg.fps
        save_config(cfg)
        if (cfg.camera, cfg.camera_source) != (old.camera, old.camera_source):
            self.apply_camera()
            if cfg.camera_source == "phone" and old.camera_source != "phone" and cfg.camera != "off":
                self.show_phone_cam()
        if cfg.preview_mode != old.preview_mode:
            self._peek.stop()
            if cfg.preview_mode == "auto" and self.streaming:
                self.peek_preview()
            else:
                self._set_preview(cfg.preview_mode != "off")
        if cfg.language != old.language:
            set_language(cfg.language)
            self.switch(cfg.view_mode, force=True)

    def apply_camera(self) -> None:
        """Start, stop or resize the virtual webcam to match the settings."""
        from .virtual_camera import CAMERA_FPS, SIZES, VirtualCamera
        old = self.server.camera or self.camera
        self.server.camera = None             # the video thread stops pushing first
        if self.phone_link is not None:
            self.phone_link.stop()
            self.phone_link = None
        self.camera = None
        if old is not None:
            old.stop()
        if self.cfg.camera == "off":
            return
        cam = VirtualCamera(self.cfg.camera, CAMERA_FPS, T("Waiting for the phone…"))
        if not cam.start():
            self.receiver.log_line.emit(T("Virtual camera could not start: {err}").format(err=T(cam.error)))
            self.cfg = self.cfg.with_changes(camera="off")
            self.window._cfg = self.cfg
            save_config(self.cfg)
            QMessageBox.warning(self.window, T("Virtual camera"),
                                T("Virtual camera could not start: {err}").format(err=T(cam.error)))
            return
        self.camera = cam
        if self.cfg.camera_source == "phone":
            self._start_phone_link(cam)
        else:
            if self.streaming:
                cam.push_live()
            self.server.camera = cam
        w, h = SIZES[self.cfg.camera]
        self.receiver.log_line.emit(T("Virtual camera on: {w}×{h}, {fps} fps").format(w=w, h=h, fps=CAMERA_FPS))

    def _start_phone_link(self, cam) -> None:
        """Picture straight from the phone_cam page (no mirroring, so no camera-app buttons)."""
        from .phone_camera import PhoneCamLink, new_room
        if not self.cfg.camera_room:
            self.cfg = self.cfg.with_changes(camera_room=new_room())
            self.window._cfg = self.cfg
            save_config(self.cfg)
        cam.fill = True                       # a camera picture: fill the frame, no bars
        link = PhoneCamLink(self.cfg.camera_room, cam.push)
        link.on_end = cam.stream_ended
        link.state_changed.connect(self._on_phone_state)
        self.phone_link = link
        link.start()

    def _on_phone_state(self, state: str) -> None:
        msg = {"live": "Phone camera connected ✓", "offline": "Cannot reach the server. Check the internet on this PC.",
               "waiting": "Phone camera: waiting for the phone…"}.get(state)
        if msg:
            self.receiver.log_line.emit(T(msg))

    def phone_state(self) -> str:
        """For feedback: the phone camera's state and picture size ("" when not in use)."""
        link = self.phone_link
        if link is None:
            return ""
        w, h = link.size
        return f"{link.state} {w}x{h}" if w else link.state

    def show_phone_cam(self) -> None:
        from .phone_cam_dialog import PhoneCamDialog
        from .phone_camera import phone_url
        if self.phone_link is None:
            return
        PhoneCamDialog(phone_url(self.cfg.camera_room, self.cfg.camera), self.phone_link, self.window).exec()

    def switch(self, mode: str, force: bool = False) -> None:
        old = self.window
        if isinstance(old, WINDOW_CLASSES[mode]) and not force:
            return
        old._cfg = self.cfg            # the window may hold older settings than ours
        old.save_geometry()            # → on_config with the saved position
        self.cfg = self.cfg.with_changes(view_mode=mode)
        self.receiver.update_config(self.cfg)
        save_config(self.cfg)
        new = self._make(mode)
        new.set_link(self.link)
        new.set_status(self.status)
        if self.last_image is not None:
            new.show_frame(self.last_image)
        self.window = new
        new.show()
        old.close()
        old.deleteLater()

    # --- events from the receiver and the video ---------------------------------------
    def on_frame(self, image) -> None:
        if not self.preview_on:
            return
        self.last_image = image
        self.window.show_frame(image)

    def _set_preview(self, on: bool) -> None:
        """Picture in the window on/off. Off = no frame is converted or drawn."""
        self.preview_on = on
        self.server.preview_enabled = on
        if not on:
            self.last_image = None
            self.window.set_streaming(False)
            if self.streaming:
                self.set_status("preview_off")
        elif self.status == "preview_off":
            self.set_status("running")

    def peek_preview(self) -> None:
        """Show the picture (and the window) for one minute, then hide again (auto mode)."""
        self._set_preview(True)
        self.show_window()
        if self.cfg.preview_mode == "auto" and self.streaming:
            self._peek.start()

    def _end_peek(self) -> None:
        if self.cfg.preview_mode != "auto" or not self.streaming:
            return
        self._set_preview(False)
        fold(self.window)                    # minimize, and make sure it really leaves the screen

    def on_stream(self, active: bool) -> None:
        self.streaming = active
        mode = self.cfg.preview_mode
        if active:
            if mode == "auto":
                self.peek_preview()          # connected: show it works for a minute
            else:
                self._set_preview(mode == "on")
            return
        # Disconnected.
        self._peek.stop()
        self.last_image = None
        self.window.set_streaming(False)
        self._set_preview(mode != "off")
        if self.receiver.is_running():
            # Back to the waiting screen of the phone type in use.
            self.set_status("android_waiting" if self.cfg.source == "android" else "running")
        if mode == "auto":
            self.show_window()               # pop up so the streamer sees it dropped

    def show_window(self) -> None:
        w = self.window
        if w.isMinimized() or not w.isVisible():
            w.showNormal()
        w.raise_()
        w.activateWindow()

    def set_status(self, status: str) -> None:
        self.status = status
        self.window.set_status(status)

    def set_link(self, link) -> None:
        self.link = link
        self.window.set_link(link)

    def activate(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__fork_by__)
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    if notify_running_instance():
        return 0   # already running — that window shows itself
    instance = InstanceServer()
    instance.listen()

    cfg = load_config()
    set_language(cfg.language)
    # Locked until the streamer signs in with an Obsidian Hub account (free plan works).
    from .account import Account
    from .login_dialog import LoginDialog
    account = Account()
    if not LoginDialog(account).run():
        return 0
    receiver = SourceManager(cfg)   # iPhone (AirPlay) or Android (USB), picked in the menu
    server = VideoServer(cfg.video_port, use_gpu=cfg.use_gpu)
    web = None
    if cfg.web_enabled:
        web = WebSource(cfg.web_port)
        if web.start():
            server.sink = web.hub.feed
            server.sink_end = web.hub.end
            server.repair = Repairer(web.hub.fix_wanted, web.hub.publish_fixed, fps=cfg.fps)
    display = DisplayController(cfg, receiver, server, web)
    updates = UpdateController(display)
    display.updates = updates
    display.window._updates = updates
    display.account = account
    display.window._account = account
    links = LinkMonitor()

    def on_frame() -> None:
        image = server.take_image()
        if image is not None:
            display.on_frame(image)

    server.frame_ready.connect(on_frame)
    server.stream_started.connect(lambda: display.on_stream(True))
    server.stream_ended.connect(lambda: display.on_stream(False))
    server.stream_started.connect(lambda: updates.on_stream(True))
    server.stream_ended.connect(lambda: updates.on_stream(False))
    server.server_error.connect(lambda msg: (receiver.log_line.emit(msg), display.set_status("error")))
    server.decoder_kind.connect(lambda kind: receiver.log_line.emit(T("Decoder: {name}").format(
        name=T("graphics card") if kind == "gpu" else T("processor (CPU)"))))
    if server.repair is not None:
        # Called from the video thread: emit through the receiver's Qt signal.
        server.repair.on_start = lambda name: receiver.log_line.emit(
            T("Late OBS viewer: re-encoding with {name}").format(name=name))
    receiver.status_changed.connect(display.set_status)
    receiver.client_event.connect(lambda ev: display.set_status("connecting") if ev == "connecting" else None)
    receiver.log_line.connect(lambda line: display.window.append_log(line))

    def on_link(link) -> None:
        display.set_link(link)
        receiver.log_line.emit(T("Direct connection to the iPhone: {link}").format(link=link) if link
                               else T("Direct connection to the iPhone: none"))
        # A new network interface: restart UxPlay so its mDNS announcement also reaches
        # the cable link. Never during mirroring.
        if (link is not None and display.cfg.source == "iphone" and receiver.is_running()
                and not display.streaming):
            receiver.restart()

    links.link_changed.connect(on_link)
    instance.activate_requested.connect(display.activate)

    def shutdown() -> None:
        cam, server.camera = display.camera or server.camera, None
        if display.phone_link is not None:
            display.phone_link.stop()
        if cam is not None:
            cam.stop()
        receiver.stop()
        server.stop()
        if web is not None:
            web.stop()
        display.window.save_geometry()
        save_config(display.cfg)

    app.aboutToQuit.connect(shutdown)
    server.start()
    receiver.start()
    if web is not None:
        receiver.log_line.emit(T("OBS link: {url}").format(url=web.url) if web.running
                               else T("OBS link is off (port {port} is busy).").format(port=cfg.web_port))
    display.window.show()
    links.start()
    updates.start()
    if cfg.camera != "off":
        display.apply_camera()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
