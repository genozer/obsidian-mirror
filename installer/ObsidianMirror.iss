; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Сорокин Иван (sorokin dev)
; Modified 2026-11-20 by Obsidian Stream Hub: Obsidian Mirror name and new AppId, virtual camera
; registration, firewall rule for the phone camera, English/Thai text.
; Obsidian Mirror installer (Inno Setup 6). Built by setup\build_installer.ps1 after setup\build_exe.ps1.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef FileVersion
  #define FileVersion "1.0.0.0"
#endif
#define AppName "Obsidian Mirror"
#define AppExe "Obsidian Mirror.exe"
#define SourceDir "..\dist\Obsidian Mirror"
#define CamDir "_internal\vendor\camera"
#define FirewallRule "Obsidian Mirror (AirPlay)"
#define FirewallRuleCam "Obsidian Mirror (phone camera)"

[Setup]
; Own AppId: never the same as the original iPhone Mirror, so both can be installed side by side.
AppId={{EA90A23D-79F6-4753-BC5C-559765AAACF4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} (beta)
AppPublisher=Obsidian Stream Hub
AppPublisherURL=https://obs-hub.web.app/
AppSupportURL=https://obs-hub.web.app/
AppCopyright=© 2026 Сорокин Иван (sorokin dev) · modified by Obsidian Stream Hub · GPL-3.0
VersionInfoVersion={#FileVersion}
VersionInfoCompany=Obsidian Stream Hub
VersionInfoCopyright=© 2026 Сорокин Иван (sorokin dev) · GPL-3.0
VersionInfoDescription=Obsidian Mirror setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Admin only: the virtual camera is registered for the whole PC (DirectShow) and the firewall
; rules are machine-wide. The in-app update runs this with /SILENT and Windows asks once (UAC).
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ObsidianMirror-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
; ultra64 does not fit in the memory of 32-bit ISCC: max + a separate compression process.
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
; Close only our own programs (Obsidian Mirror, UxPlay, adb) during an update. Checking the
; DLLs too made Restart Manager list TikTok LIVE Studio and Chrome (they keep the virtual
; camera DLL open); they cannot be closed and the silent update gave up without a word
; (1.4.0-obs.4 on 2026-11-20). The camera DLLs are replaced at the next restart instead.
; "force": no question box (it is hidden in /SILENT and its default is Abort).
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.Firewall=Allow Obsidian Mirror through Windows Firewall (home network only) — needed for AirPlay and the phone camera
english.Launch=Start Obsidian Mirror
english.Camera=Add the virtual camera "Obsidian Mirror Camera" (for TikTok LIVE Studio, OBS, Discord…)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "firewall"; Description: "{cm:Firewall}"
Name: "camera"; Description: "{cm:Camera}"

[Files]
; The camera DLLs may be in use (TikTok LIVE Studio keeps the camera open) during an update:
; replaced at the next restart instead of failing the update.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "{#CamDir}\*.dll"; \
  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\{#CamDir}\obsidian_camera64.dll"; DestDir: "{app}\{#CamDir}"; \
  Flags: ignoreversion restartreplace uninsrestartdelete
Source: "{#SourceDir}\{#CamDir}\obsidian_camera32.dll"; DestDir: "{app}\{#CamDir}"; \
  Flags: ignoreversion restartreplace uninsrestartdelete
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Virtual camera for 64- and 32-bit apps (OBS is 64-bit, some older apps 32-bit).
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{app}\{#CamDir}\obsidian_camera64.dll"""; \
  Flags: runhidden; Tasks: camera
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s ""{app}\{#CamDir}\obsidian_camera32.dll"""; \
  Flags: runhidden; Tasks: camera
; Remove old rules first (reinstall / update does not pile up duplicates).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRuleCam}"""; Flags: runhidden; Tasks: firewall
; Windows often marks the home network "public", and the iPhone USB network always is:
; any profile, but only devices on the local subnet (never the internet).
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow profile=any remoteip=localsubnet program=""{app}\_internal\uxplay\bin\uxplay.exe"" enable=yes"; \
  Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow profile=any remoteip=localsubnet program=""{app}\_internal\uxplay\bin\uxplay-bonjour.exe"" enable=yes"; \
  Flags: runhidden; Tasks: firewall
; Phone camera (WebRTC): the phone on the same Wi‑Fi sends its picture straight to the program.
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""{#FirewallRuleCam}"" dir=in action=allow protocol=udp profile=any remoteip=localsubnet program=""{app}\{#AppExe}"" enable=yes"; \
  Flags: runhidden; Tasks: firewall
Filename: "{app}\{#AppExe}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; In-app update (app/updater.py runs this installer with /SILENT): start the program again.
; runasoriginaluser: not as admin, even though the installer itself was elevated.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
; Runs before the files are removed.
Filename: "{sys}\regsvr32.exe"; Parameters: "/s /u ""{app}\{#CamDir}\obsidian_camera64.dll"""; \
  Flags: runhidden; RunOnceId: "DelCam64"
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s /u ""{app}\{#CamDir}\obsidian_camera32.dll"""; \
  Flags: runhidden; RunOnceId: "DelCam32"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; \
  Flags: runhidden; RunOnceId: "DelFirewall"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRuleCam}"""; \
  Flags: runhidden; RunOnceId: "DelFirewallCam"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\{#AppName}"

[Code]
var
  Installed: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Installed := True;
end;

// In-app update that did not finish (cancelled, error): the program had already closed
// itself, so start the version that is still installed instead of leaving nothing on screen.
procedure DeinitializeSetup();
var
  Exe: String;
  Rc: Integer;
begin
  if WizardSilent and not Installed then
  begin
    try
      Exe := ExpandConstant('{app}\{#AppExe}');
      if FileExists(Exe) then
        ExecAsOriginalUser(Exe, '', ExtractFileDir(Exe), SW_SHOWNORMAL, ewNoWait, Rc);
    except
    end;
  end;
end;
