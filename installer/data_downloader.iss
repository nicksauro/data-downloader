; data-downloader InnoSetup script
; Story 4.17 — Pichau directive 2026-05-06 (integrate installer in v1.0.5)
; Owner: Felix | Architect: Aria (InnoSetup decision, ADR-021)
; Pax+Aria mini-council 2026-05-06: integrar na v1.0.5 (override v1.1.0).
;
; Build: invoked by ``scripts/build_release.py --with-installer``.
; Optional override: ``ISCC.exe /DAppVersion=X.Y.Z installer\data_downloader.iss``
;
; AC mapping (Story 4.17):
;   AC1 — sections [Setup], [Files], [Icons], [Tasks], [UninstallDelete], [Code]
;   AC2 — output ``..\dist\data-downloader-Setup-vX.Y.Z.exe``
;   AC3 — DefaultDirName = {localappdata}\Programs\data-downloader (no admin)
;   AC4 — Start Menu always; Desktop via [Tasks] desktopicon
;   AC5 — Add/Remove Programs entry auto-generated (UninstallDisplayName/Icon)
;   AC6 — uninstaller preserva ~/.data-downloader/ (fora do escopo [Files])
;   AC7 — github_release.py uploada Setup.exe junto ao zip

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

#define AppName "data-downloader"
#define AppPublisher "data-downloader squad"
#define AppURL "https://github.com/nicksauro/data-downloader"
#define AppExeName "data_downloader.exe"
#define AppCliExeName "data_downloader-cli.exe"

[Setup]
AppId={{8A3D7B2C-9F4A-4E1B-A6F5-C8D2E5A7B9C3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=data-downloader-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
SetupLogging=yes
ShowLanguageDialog=auto
WizardSizePercent=100,100
; Mantemos cleanup automatico do dir de install no uninstall (preserva user data
; em ~/.data-downloader que vive em {userprofile}, fora do {app}).
UsePreviousAppDir=yes
UsePreviousGroup=yes
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; Bundle PyInstaller --onedir output (gerado por scripts/build_release.py).
; Caminho relativo ao .iss: ..\dist\data_downloader\
Source: "..\dist\data_downloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{#AppName} (CLI)"; Filename: "{app}\{#AppCliExeName}"; WorkingDir: "{app}"; Comment: "Linha de comando explicita"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpeza extra opcional dentro de {app}. NAO removemos a pasta de profiles
; em userprofile (~/.data-downloader) — preservar credenciais (AC6).
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\logs"

[Code]
function InitializeUninstall(): Boolean;
var
  Response: Integer;
begin
  Result := True;
  Response := MsgBox(
    'Suas credenciais e configuracoes em %USERPROFILE%\.data-downloader\ serao PRESERVADAS por padrao.' #13#10 #13#10 +
    'Reinstalando o data-downloader, suas configuracoes voltam automaticamente.' #13#10 #13#10 +
    'Para remover tudo manualmente, delete a pasta %USERPROFILE%\.data-downloader\ apos o uninstall.' #13#10 #13#10 +
    'Continuar com a desinstalacao?',
    mbConfirmation, MB_YESNO);
  if Response = IDNO then
    Result := False;
end;
