#ifndef AppVersion
  #define AppVersion "0.3.0-alpha"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\LinguaRelay"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef ModelPackDir
  #define ModelPackDir ""
#endif

#define AppName "LinguaRelay"
#define AppPublisher "LinguaRelay contributors"
#define AppURL "https://github.com/MuzeAnisichael/LinguaRelay"
#define AppExeName "LinguaRelay.exe"

[Setup]
AppId={{B40F672E-4591-43D6-8657-4D4A71F337E5}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=LinguaRelay-{#AppVersion}-Setup-x64
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked
Name: "startup"; Description: "登录 Windows 后启动 LinguaRelay"; GroupDescription: "启动选项："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#if ModelPackDir != ""
Source: "{#ModelPackDir}\*"; DestDir: "{localappdata}\LinguaRelay\models"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
