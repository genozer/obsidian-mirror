# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Сорокин Иван (sorokin dev)
# Modified 2026-11-20 by Obsidian Stream Hub: Obsidian Mirror name, choice of Python, no auto-install.
# Builds dist\ObsidianMirror-Setup-<version>.exe (Inno Setup 6).
# Build the app first: setup\build_exe.ps1 (or pass -BuildExe).
# Run:  powershell -ExecutionPolicy Bypass -File setup\build_installer.ps1 [-BuildExe] [-Python <python.exe>]
# Inno Setup 6 must be installed (winget install -e --id JRSoftware.InnoSetup).
param([switch]$BuildExe, [string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = if ($Python) { $Python } else { Join-Path $root ".venv\Scripts\python.exe" }

if ($BuildExe) {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_exe.ps1") -Python $py
    if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 failed" }
}
if (-not (Test-Path (Join-Path $root "dist\Obsidian Mirror\Obsidian Mirror.exe"))) {
    throw "No dist\Obsidian Mirror - run setup\build_exe.ps1 first (or add -BuildExe)"
}

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found: winget install -e --id JRSoftware.InnoSetup" }

$version = (& $py -c "import sys; sys.path.insert(0, r'$root'); import app; print(app.__version__)").Trim()
Write-Host "==> Building the installer v$version" -ForegroundColor Cyan
$fileVersion = ((([regex]::Matches($version, "\d+") | ForEach-Object Value) + "0", "0", "0", "0") | Select-Object -First 4) -join "."
& $iscc "/DAppVersion=$version" "/DFileVersion=$fileVersion" (Join-Path $root "installer\ObsidianMirror.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$setup = Join-Path $root "dist\ObsidianMirror-Setup-$version.exe"
Write-Host ""
Write-Host ("Done: {0}  ({1:N1} MB)" -f $setup, ((Get-Item $setup).Length / 1MB)) -ForegroundColor Green
