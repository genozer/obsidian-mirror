# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
# Downloads the official scrcpy release (Genymobile, Apache-2.0) for Android support:
# adb.exe + its DLLs + scrcpy-server, checks the SHA-256 from the release, and puts them
# in vendor\scrcpy. Run:  powershell -ExecutionPolicy Bypass -File setup\get_scrcpy.ps1
$ErrorActionPreference = "Stop"
$Version = "5.0.1"          # must match SCRCPY_VERSION in app\android_source.py
$Zip = "scrcpy-win64-v$Version.zip"
$Base = "https://github.com/Genymobile/scrcpy/releases/download/v$Version"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "vendor\scrcpy"
$Tmp = Join-Path $env:TEMP "obsidian-mirror-scrcpy"
New-Item -ItemType Directory -Force $Tmp, $Out | Out-Null

Invoke-WebRequest "$Base/$Zip" -OutFile "$Tmp\$Zip"
Invoke-WebRequest "$Base/SHA256SUMS.txt" -OutFile "$Tmp\SHA256SUMS.txt"
$expected = (Select-String -Path "$Tmp\SHA256SUMS.txt" -Pattern ([regex]::Escape($Zip))).Line.Split(" ")[0]
$actual = (Get-FileHash "$Tmp\$Zip" -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) { throw "SHA-256 mismatch for $Zip ($actual, expected $expected)" }

Expand-Archive "$Tmp\$Zip" -DestinationPath $Tmp -Force
$src = Join-Path $Tmp "scrcpy-win64-v$Version"
foreach ($f in "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "scrcpy-server", "LICENSE.txt") {
    Copy-Item (Join-Path $src $f) $Out -Force
}
Write-Host "scrcpy $Version -> $Out" -ForegroundColor Green
