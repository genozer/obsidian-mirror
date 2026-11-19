# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
# Adds (or with -Remove, removes) "Obsidian Mirror Camera" to Windows for 64- and 32-bit apps.
# DirectShow cameras are listed for the whole PC, so this needs admin rights (asks with UAC).
# The installer does the same in round 2; this script is for the lab.
#   powershell -ExecutionPolicy Bypass -File native\register_camera.ps1 [-Remove]
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$dir = Join-Path (Split-Path -Parent $PSScriptRoot) "vendor\camera"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($Remove) { $argv += "-Remove" }
    $p = Start-Process powershell -Verb RunAs -ArgumentList $argv -Wait -PassThru -WindowStyle Hidden
    exit $p.ExitCode
}
$flag = if ($Remove) { "/u" } else { "" }
$jobs = @(@{Exe = "$env:WINDIR\System32\regsvr32.exe"; Dll = "obsidian_camera64.dll"},
          @{Exe = "$env:WINDIR\SysWOW64\regsvr32.exe"; Dll = "obsidian_camera32.dll"})
$code = 0
foreach ($j in $jobs) {
    $dll = Join-Path $dir $j.Dll
    if (-not (Test-Path $dll)) { continue }
    $a = @("/s") + $(if ($flag) { @($flag) } else { @() }) + @("`"$dll`"")
    $r = Start-Process $j.Exe -ArgumentList $a -Wait -PassThru
    if ($r.ExitCode -ne 0) { $code = $r.ExitCode }
}
exit $code
