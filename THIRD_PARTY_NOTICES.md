# Third-party components / Сторонние компоненты

**iPhone Mirror** — © 2026 Сорокин Иван / Ivan Sorokin (**sorokin dev**).
Licensed under GPL-3.0-or-later (see `LICENSE`) / распространяется под GPL-3.0-or-later.

The app build (.exe and installer) bundles the following components /
сборка (.exe и установщик) включает следующие компоненты:

| Component / Компонент | License / Лицензия | Source / Исходный код |
|---|---|---|
| UxPlay (AirPlay receiver) | GPL-3.0 | https://github.com/FDH2/UxPlay |
| GStreamer + plugins (base/good/bad/libav) | LGPL-2.1+ | https://gstreamer.freedesktop.org/src/ |
| FFmpeg (in gst-libav and PyAV) | LGPL-2.1+ / GPL-2.0+ (build-dependent) | https://ffmpeg.org/download.html |
| libplist | LGPL-2.1+ | https://github.com/libimobiledevice/libplist |
| OpenSSL | Apache-2.0 | https://www.openssl.org/source/ |
| Other MSYS2 DLLs (glib, pango, cairo, …) | various free licenses | https://packages.msys2.org/ |
| `dns_sd.h` (Apple mDNSResponder, build-time only) | BSD-3-Clause | https://github.com/apple-oss-distributions/mDNSResponder |
| Qt 6 / PySide6 | LGPL-3.0 | https://code.qt.io/ |
| PyAV | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| Python | PSF License | https://www.python.org/ |

UxPlay and GStreamer binaries are built from source by `setup/install.ps1`,
`setup/build_uxplay.sh`, `setup/build_uxplay_bonjour.sh` and `setup/bundle_uxplay.sh`.
The Bonjour runtime (`dnssd.dll`) is **not** redistributed — it is used only if already installed.

The "sorokin dev" logo is © Сорокин Иван and is not covered by the GPL.
Логотип «sorokin dev» принадлежит Сорокину Ивану и не распространяется под GPL.

AirPlay and iPhone are trademarks of Apple Inc. This project is not affiliated with or endorsed by Apple.
AirPlay и iPhone — торговые марки Apple Inc. Проект не связан с Apple и не одобрен ею.

## scrcpy (Android support, Obsidian Mirror fork)

scrcpy-server and adb from the official scrcpy release v5.0.1 — Copyright (C) 2018 Genymobile,
Copyright (C) 2018-2026 Romain Vimont — Apache License 2.0 (https://github.com/Genymobile/scrcpy).
Downloaded by setup/get_scrcpy.ps1 into vendor/scrcpy (with its LICENSE.txt); not stored in git.
adb is part of the Android SDK Platform-Tools (Apache License 2.0).

## softcam (virtual camera)

native/softcam — softcam v1.8.1, Copyright (c) 2020 tshino — MIT License (native/softcam/LICENSE,
https://github.com/tshino/softcam). Includes Microsoft DirectShow BaseClasses (MIT, from the Windows
SDK samples). Modified by Obsidian Stream Hub: own camera name, CLSID and shared-memory names, and a
new `scIdleSeconds` call (native/softcam/CHANGES_OBSIDIAN.md). Built into vendor/camera
(obsidian_camera64.dll / obsidian_camera32.dll) with the MIT license next to it.

## Phone camera link (WebRTC + Socket.IO client)

app/phone_camera.py receives the obs-hub phone camera page over WebRTC. Python packages used, each
under its own license (installed from PyPI, not copied into this repository):
aiortc 1.16.0 and aioice (BSD-3-Clause, Jeremy Lainé), pylibsrtp (BSD-3-Clause; bundles libsrtp,
BSD-3-Clause, Cisco Systems), pyee (MIT), python-socketio and python-engineio (MIT, Miguel Grinberg),
aiohttp, yarl, multidict, frozenlist, aiosignal, propcache, aiohappyeyeballs (Apache-2.0, aio-libs),
pyOpenSSL (Apache-2.0), google-crc32c (Apache-2.0), dnspython (ISC), ifaddr (MIT), bidict (MPL-2.0),
simple-websocket and wsproto (MIT), h11 (MIT), attrs (MIT). The installer must ship their license files.
