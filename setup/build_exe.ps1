# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-20 by Obsidian Stream Hub: Obsidian Mirror name, phone camera (aiortc),
# virtual camera DLLs, Android (scrcpy), choice of Python.
# Builds the portable app: dist\Obsidian Mirror\Obsidian Mirror.exe
# Needs: UxPlay built (setup\install.ps1), vendor\camera (native\build_camera.ps1),
#        vendor\scrcpy (setup\get_scrcpy.ps1), a Python with requirements.txt installed.
# Run:  powershell -ExecutionPolicy Bypass -File setup\build_exe.ps1 [-Python <python.exe>]
param([string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$name = "Obsidian Mirror"
$py = if ($Python) { $Python } else { Join-Path $root ".venv\Scripts\python.exe" }
$bash = "C:\msys64\usr\bin\bash.exe"
$bundle = Join-Path $root "build\uxplay_bundle"

if (-not (Test-Path $py)) { throw "No Python at $py - run setup\install.ps1 or pass -Python" }
if (-not (Test-Path "C:\msys64\ucrt64\bin\uxplay.exe")) { throw "UxPlay is not built - run setup\install.ps1" }
foreach ($need in "vendor\camera\obsidian_camera64.dll", "vendor\camera\obsidian_camera32.dll",
                  "vendor\scrcpy\adb.exe", "vendor\scrcpy\scrcpy-server") {
    if (-not (Test-Path (Join-Path $root $need))) { throw "Missing $need (native\build_camera.ps1 / setup\get_scrcpy.ps1)" }
}

Write-Host "==> [1/4] PyInstaller" -ForegroundColor Cyan
& $py -m pip install --upgrade "pyinstaller>=6.10"
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller" }

Write-Host "==> [2/4] UxPlay + GStreamer bundle" -ForegroundColor Cyan
$env:MSYSTEM = "UCRT64"
$env:CHERE_INVOKING = "1"
Push-Location $PSScriptRoot
[Environment]::CurrentDirectory = $PSScriptRoot
try {
    & $bash -lc "bash ./bundle_uxplay.sh ../build/uxplay_bundle"
    if ($LASTEXITCODE -ne 0) { throw "UxPlay bundle failed" }
} finally { Pop-Location }

Write-Host "==> [3/4] Icon, version info" -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot "make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Could not make the icon" }
$versionFile = Join-Path $root "build\version_info.txt"
& $py (Join-Path $PSScriptRoot "version_info.py") $versionFile
if ($LASTEXITCODE -ne 0) { throw "Could not write the version file" }

Write-Host "==> [4/4] Build the .exe" -ForegroundColor Cyan
Push-Location $root
[Environment]::CurrentDirectory = $root
try {
    # aiortc/aioice/pylibsrtp: phone camera (WebRTC) · socketio/engineio: its signalling
    # (both imported inside functions, collect them whole so nothing is missed at run time).
    & $py -m PyInstaller --noconfirm --clean --windowed `
        --name $name `
        --icon (Join-Path $root "assets\icon.ico") `
        --version-file $versionFile `
        --add-data ((Join-Path $root "assets") + ";assets") `
        --collect-all aiortc --collect-all aioice --collect-all pylibsrtp `
        --collect-submodules socketio --collect-submodules engineio `
        --hidden-import aiohttp --hidden-import segno `
        --exclude-module tkinter `
        --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
        --exclude-module PySide6.QtPdf `
        --distpath dist --workpath "build\pyinstaller" --specpath build `
        iphone_mirror.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally { Pop-Location }

$internal = Join-Path $root "dist\$name\_internal"

# Copied after PyInstaller: otherwise it "analyses" these DLLs and duplicates them
# into the root of _internal (+~180 MB).
Write-Host "    Copying UxPlay, camera and scrcpy into the build..."
Copy-Item $bundle (Join-Path $internal "uxplay") -Recurse -Force
New-Item -ItemType Directory -Force (Join-Path $internal "vendor") | Out-Null
foreach ($v in "camera", "scrcpy") {
    Copy-Item (Join-Path $root "vendor\$v") (Join-Path $internal "vendor\$v") -Recurse -Force
}

# Qt parts the app does not use (QML/Quick, PDF, networking/TLS, software OpenGL,
# Qt's own ffmpeg, extra platforms).
$qt = Join-Path $internal "PySide6"
$unused = @(
    "opengl32sw.dll", "Qt6Pdf.dll", "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll", "Qt6Quick.dll", "Qt6VirtualKeyboard.dll",
    "avcodec-*.dll", "avformat-*.dll", "avutil-*.dll", "swresample-*.dll", "swscale-*.dll",
    "plugins\imageformats\qpdf.dll", "plugins\platforminputcontexts", "plugins\tls",
    "plugins\networkinformation", "plugins\generic", "plugins\platforms\qdirect2d.dll",
    "plugins\platforms\qminimal.dll", "plugins\platforms\qoffscreen.dll"
)
foreach ($item in $unused) {
    Get-ChildItem (Join-Path $qt $item) -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
}

$exe = Join-Path $root "dist\$name\$name.exe"
$size = [math]::Round(((Get-ChildItem (Split-Path $exe) -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "Done: $exe  ($size MB)" -ForegroundColor Green
Write-Host "The whole 'dist\$name' folder runs on another PC without Python or MSYS2."
Write-Host "The virtual camera still has to be registered once (the installer does it)."
