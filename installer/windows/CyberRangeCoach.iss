#define AppName "Cyber Range Coach"
#define AppVersion "2.0.0-alpha.1"
#define AppPublisher "Cyber Range Coach"
#define AppExeName "CyberRangeCoach.exe"

[Setup]
AppId={{9A5B7044-A9C1-4DB0-84F7-C99F8E3C6E24}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Cyber Range Coach
DefaultGroupName={#AppName}
PrivilegesRequired=admin
OutputDir=..\..\dist\installer
OutputBaseFilename=CyberRangeCoach-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "trustcert"; Description: "Доверять локальному CA только на этом Windows-ноутбуке"; Flags: unchecked
Name: "firewallui"; Description: "Разрешить доступ к академии по TCP 8443 только в Private LAN"; Flags: unchecked

[Files]
Source: "..\..\dist\CyberRangeCoach\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "configure-firewall.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "remove-firewall.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\Cyber Range Coach"; Filename: "{app}\{#AppExeName}"; Parameters: "serve --lan"
Name: "{group}\Cyber Range Coach Doctor"; Filename: "{app}\CyberRangeCoachDoctor.exe"

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: "setup --generate-certificate"; StatusMsg: "Создаём локальный сертификат в профиле вошедшего пользователя..."; Flags: runhidden waituntilterminated runasoriginaluser
Filename: "{app}\{#AppExeName}"; Parameters: "setup --trust-certificate"; StatusMsg: "Добавляем локальный CA в хранилище вошедшего пользователя..."; Tasks: trustcert; Flags: runhidden waituntilterminated runasoriginaluser
Filename: "powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\tools\configure-firewall.ps1"" -Mode Academy -ApplicationPath ""{app}\{#AppExeName}"" -Approve"; StatusMsg: "Создаём правило только для Private LAN..."; Tasks: firewallui; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExeName}"; Parameters: "serve --lan"; Description: "Запустить Cyber Range Coach"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\tools\remove-firewall.ps1"" -Approve"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveCyberRangeCoachFirewall"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Log('Пользовательские данные в LocalAppData намеренно сохраняются при удалении приложения.');
end;
