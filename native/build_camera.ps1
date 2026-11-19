# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
# Builds the virtual camera (softcam, MIT, renamed "Obsidian Mirror Camera") for 64- and 32-bit apps.
# Needs Visual Studio Build Tools with C++ (any version that has MSBuild + MSVC).
#   powershell -ExecutionPolicy Bypass -File native\build_camera.ps1
# Output: vendor\camera\obsidian_camera64.dll, obsidian_camera32.dll (+ LICENSE.txt)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path -Parent $here
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "Visual Studio Build Tools with C++ not found" }
$msbuild = Join-Path $vs "MSBuild\Current\Bin\amd64\MSBuild.exe"
# Use the newest toolset that is installed (the project says v143).
$toolset = (Get-ChildItem (Join-Path $vs "MSBuild\Microsoft\VC") -Directory |
            ForEach-Object { Get-ChildItem (Join-Path $_.FullName "Platforms\x64\PlatformToolsets") -Directory -ErrorAction SilentlyContinue } |
            Where-Object { $_.Name -match '^v\d+$' } | Sort-Object Name | Select-Object -Last 1).Name
$out = Join-Path $root "vendor\camera"
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($p in @(@{Platform = "x64"; Name = "obsidian_camera64.dll"}, @{Platform = "Win32"; Name = "obsidian_camera32.dll"})) {
    Write-Host "==> $($p.Platform) ($toolset)" -ForegroundColor Cyan
    $bin = Join-Path $here ("build\" + $p.Platform + "\")
    & $msbuild (Join-Path $here "softcam\src\softcam\softcam.vcxproj") /nologo /v:minimal /m `
        /p:Configuration=Release /p:Platform=$($p.Platform) /p:PlatformToolset=$toolset `
        "/p:OutDir=$bin"
    if ($LASTEXITCODE -ne 0) { throw "build failed ($($p.Platform))" }
    Copy-Item (Join-Path $bin "softcam.dll") (Join-Path $out $p.Name) -Force
}
Copy-Item (Join-Path $here "softcam\LICENSE") (Join-Path $out "LICENSE.txt") -Force
Get-ChildItem $out | Select-Object Name, Length
