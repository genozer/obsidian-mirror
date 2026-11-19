# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-19 by Obsidian Stream Hub (language, GPU, preview, OBS link, update and camera settings; new receiver name).
"""Настройки приложения: неизменяемый dataclass + загрузка/сохранение в config.json."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from .paths import user_data_dir

log = logging.getLogger(__name__)

CONFIG_PATH = user_data_dir() / "config.json"

SCALE_MIN = 0.3
SCALE_MAX = 1.6
PORT_MIN = 1024
PORT_MAX = 65535


@dataclass(frozen=True)
class AppConfig:
    device_name: str = "Obsidian Mirror PC"   # имя приёмника в «Повторе экрана»
    uxplay_path: str = ""                   # пусто = автопоиск
    video_port: int = 47011                 # локальный TCP-порт для видео UxPlay -> приложение
    max_resolution: str = "1920x1920"       # -s: квадрат, чтобы и портрет, и ландшафт были чёткими
    fps: int = 30                           # 30 = light (default) · 60 = smooth, for strong PCs
    audio_enabled: bool = True
    always_on_top: bool = False
    scale: float = 0.8                      # масштаб «корпуса» телефона
    model_color: str = "natural"            # natural | black | white | blue
    mdns_mode: str = "auto"                 # auto | bonjour | internal — как объявлять ПК в сети
    window_x: int = -1
    window_y: int = -1
    view_mode: str = "phone"                # phone — окно-«айфон» | window — обычное окно
    fit_mode: str = "fit"                   # fit | stretch | fill — для обычного окна
    rotation: int = 0                       # поворот картинки в обычном окне, ×90° по часовой
    mirrored: bool = False                  # зеркально по горизонтали
    plain_x: int = -1                       # геометрия обычного окна
    plain_y: int = -1
    plain_w: int = -1
    plain_h: int = -1
    language: str = "auto"                  # auto | th | en
    use_gpu: bool = True                    # decode on the graphics card (D3D11VA)
    # auto: show the picture for 1 minute after the phone connects, then hide it and
    # minimize (OBS link keeps working, ~4% of a core) · on: always · off: never
    preview_mode: str = "auto"
    source: str = "iphone"                  # iphone (AirPlay) | android (USB, scrcpy)
    adb_path: str = ""                      # empty = vendor/scrcpy/adb.exe
    scrcpy_server: str = ""                 # empty = vendor/scrcpy/scrcpy-server
    web_enabled: bool = True                # OBS Browser Source on 127.0.0.1
    web_port: int = 47080
    update_check: bool = True               # look for a new version at start and every 6 hours
    update_skip: str = ""                   # a version the user chose to skip
    update_url: str = ""                    # empty = app/updater.py DEFAULT_URL
    camera: str = "off"                     # virtual webcam: off | 720p | 1080p | portrait
    camera_source: str = "mirror"           # mirror (the mirrored screen) | phone (phone_cam page)
    camera_room: str = ""                   # random room for the phone_cam page, made on first use

    def with_changes(self, **changes) -> "AppConfig":
        return validate(replace(self, **changes))


COLORS = ("natural", "black", "white", "blue")
MDNS_MODES = ("auto", "bonjour", "internal")
VIEW_MODES = ("phone", "window")
FIT_MODES = ("fit", "stretch", "fill")
LANGUAGES = ("auto", "th", "en")
PREVIEW_MODES = ("auto", "on", "off")
SOURCES = ("iphone", "android")
CAMERA_MODES = ("off", "720p", "1080p", "portrait")
CAMERA_SOURCES = ("mirror", "phone")


def validate(cfg: AppConfig) -> AppConfig:
    """Возвращает копию с безопасными значениями (ничего не мутирует)."""
    name = cfg.device_name.strip()[:40] or AppConfig.device_name
    port = cfg.video_port if PORT_MIN <= cfg.video_port <= PORT_MAX else AppConfig.video_port
    scale = min(max(float(cfg.scale), SCALE_MIN), SCALE_MAX)
    fps = 60 if int(cfg.fps) >= 60 else 30   # only the two offered choices
    res = cfg.max_resolution if _valid_resolution(cfg.max_resolution) else AppConfig.max_resolution
    color = cfg.model_color if cfg.model_color in COLORS else AppConfig.model_color
    mdns = cfg.mdns_mode if cfg.mdns_mode in MDNS_MODES else AppConfig.mdns_mode
    view = cfg.view_mode if cfg.view_mode in VIEW_MODES else AppConfig.view_mode
    fit = cfg.fit_mode if cfg.fit_mode in FIT_MODES else AppConfig.fit_mode
    lang = cfg.language if cfg.language in LANGUAGES else AppConfig.language
    preview = cfg.preview_mode if cfg.preview_mode in PREVIEW_MODES else AppConfig.preview_mode
    source = cfg.source if cfg.source in SOURCES else AppConfig.source
    camera = cfg.camera if cfg.camera in CAMERA_MODES else AppConfig.camera
    cam_src = cfg.camera_source if cfg.camera_source in CAMERA_SOURCES else AppConfig.camera_source
    room = cfg.camera_room if re.fullmatch(r"[A-Za-z0-9_]{6,40}", cfg.camera_room or "") else ""
    web_port = cfg.web_port if PORT_MIN <= cfg.web_port <= PORT_MAX else AppConfig.web_port
    return replace(cfg, device_name=name, video_port=port, scale=scale, fps=fps,
                   max_resolution=res, model_color=color, mdns_mode=mdns,
                   view_mode=view, fit_mode=fit, rotation=int(cfg.rotation) % 4,
                   language=lang, web_port=web_port, preview_mode=preview,
                   source=source, camera=camera, camera_source=cam_src, camera_room=room)


def _valid_resolution(value: str) -> bool:
    parts = value.lower().split("x")
    return len(parts) == 2 and all(p.isdigit() and 240 <= int(p) <= 4096 for p in parts)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))   # Notepad and PowerShell 5 add a BOM
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Не удалось прочитать %s (%s), использую настройки по умолчанию", path, exc)
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    known = {f.name: f.type for f in fields(AppConfig)}
    defaults = AppConfig()
    kwargs = {}
    for key, value in raw.items():
        if key not in known:
            continue
        expected = type(getattr(defaults, key))
        if expected is float and isinstance(value, int):
            value = float(value)
        if isinstance(value, expected) and not (expected is int and isinstance(value, bool)):
            kwargs[key] = value
    return validate(AppConfig(**kwargs))


def save_config(cfg: AppConfig, path: Path = CONFIG_PATH) -> None:
    try:
        path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.error("Не удалось сохранить настройки в %s: %s", path, exc)
