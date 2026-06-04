; Meeting Minutes - Inno Setup 6 installer script
;
; Per-user install: PrivilegesRequired=lowest means NO admin rights and NO UAC
; elevation prompt are required to install. Users with admin rights may opt to
; install machine-wide via the privileges dialog (PrivilegesRequiredOverridesAllowed).
;
; All relative paths in this script (OutputDir, [Files] Source, SetupIconFile)
; are resolved relative to this script's own folder (packaging/). The freeze
; output lives at ../dist/MeetingMinutes and the installer is written to
; ../dist/installer.
;
; Build with:  ISCC.exe packaging\installer.iss   (run from the repo root)

#define AppName "Meeting Minutes"
#define AppVersion "1.0.3"
#define AppPublisher "Hawaz"
#define AppExe "MeetingMinutes.exe"

[Setup]
; Stable, hardcoded AppId GUID - DO NOT change between releases (upgrades rely on it)
AppId={{8F2C9A14-3B7E-4D62-9C5A-1E0F7A6B2D38}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\MeetingMinutes
DefaultGroupName=Meeting Minutes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
OutputDir=..\dist\installer
OutputBaseFilename=MeetingMinutes-Setup
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\MeetingMinutes\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Meeting Minutes"; Flags: nowait postinstall skipifsilent
