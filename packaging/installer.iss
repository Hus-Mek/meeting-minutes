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
#define AppVersion "1.0.6"
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
; Everything EXCEPT the bundled Claude Code CLI is always installed. The CLI files
; (the claude.* shims and the @anthropic-ai package) are excluded here and laid down
; by the conditional entries below — see Approach B in [Code].
;
; IMPORTANT: this is a PyInstaller ONEDIR (6.x) build, so all bundled data lands
; under the _internal\ contents dir (the spec maps vendor/node as `datas`, and
; desktop.py resolves it from sys._MEIPASS == _internal\). The real on-disk path is
; therefore dist\MeetingMinutes\_internal\vendor\node\... — every path below MUST
; include that _internal\ prefix or the Exclude/Check below would silently no-op and
; the bundled CLI would ship unconditionally.
Source: "..\dist\MeetingMinutes\*"; DestDir: "{app}"; Excludes: "\_internal\vendor\node\claude*,\_internal\vendor\node\node_modules\@anthropic-ai\*"; Flags: recursesubdirs createallsubdirs ignoreversion
; Approach B: ship the bundled Claude Code CLI ONLY when the target PC has no
; existing claude (ShouldInstallBundledClaude). Node.js itself is always installed
; above, so the launcher can still install/run a CLI later if needed. skipifsource...
; keeps local installer compiles working when vendor\node was not produced (dev builds).
Source: "..\dist\MeetingMinutes\_internal\vendor\node\claude*"; DestDir: "{app}\_internal\vendor\node"; Check: ShouldInstallBundledClaude; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\MeetingMinutes\_internal\vendor\node\node_modules\@anthropic-ai\*"; DestDir: "{app}\_internal\vendor\node\node_modules\@anthropic-ai"; Check: ShouldInstallBundledClaude; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Meeting Minutes"; Flags: nowait postinstall skipifsilent

[Code]
{ Approach B: detect whether this PC already has a working Claude Code CLI so the
  installer can SKIP laying down the ~95 MB bundled copy (the launcher already
  prefers an existing claude at runtime). Detection mirrors the resolution order in
  meeting_minutes/llm.py ClaudeCodeClient._FALLBACK_PATHS: PATH first (via `where`),
  then the known per-user install locations. The result is cached because Inno calls
  a Check function once PER matched file. }

var
  ExistingClaudeChecked: Boolean;
  ExistingClaudeFound: Boolean;

function ClaudeOnPath(): Boolean;
var
  ResultCode: Integer;
begin
  { `where claude` exits 0 when claude resolves on the user's PATH (e.g. the npm
    global shim dir %APPDATA%\npm). The installer runs as the user for a per-user
    install, so it sees the user's PATH. }
  Result := Exec(ExpandConstant('{cmd}'), '/C where claude', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function KnownClaudeInstallExists(): Boolean;
var
  UserProfile: String;
begin
  UserProfile := GetEnv('USERPROFILE');
  Result :=
    FileExists(ExpandConstant('{userappdata}\npm\claude.cmd')) or
    FileExists(ExpandConstant('{userappdata}\npm\claude.exe')) or
    FileExists(ExpandConstant('{localappdata}\Programs\claude\claude.exe')) or
    ((UserProfile <> '') and FileExists(UserProfile + '\.local\bin\claude.exe'));
end;

function ExistingClaudePresent(): Boolean;
begin
  if not ExistingClaudeChecked then
  begin
    ExistingClaudeFound := ClaudeOnPath() or KnownClaudeInstallExists();
    ExistingClaudeChecked := True;
  end;
  Result := ExistingClaudeFound;
end;

function ShouldInstallBundledClaude(): Boolean;
begin
  { Install the bundled CLI only when the PC has none of its own. }
  Result := not ExistingClaudePresent();
end;
