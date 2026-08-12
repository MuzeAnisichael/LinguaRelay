#ifndef AppVersion
  #define AppVersion "0.1.2"
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
#define AppPublisher "Leeleelee"
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
InfoBeforeFile=..\docs\PRIVACY.zh-CN.md
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
SetupIconFile=..\assets\linguarelay.ico

[Languages]
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
Name: "{autoprograms}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  ModelCheckReported: Boolean;
  RemoveModelsOnUninstall: Boolean;

function ExistingModelsDetected(): Boolean;
var
  ModelRoot: String;
begin
  ModelRoot := ExpandConstant('{localappdata}\LinguaRelay\models');
  Result :=
    FileExists(ModelRoot + '\models--Systran--faster-whisper-small\snapshots\536b0662742c02347bc0e980a01041f333bce120\model.bin') and
    FileExists(ModelRoot + '\m2m100_418m_ct2\model.bin');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpReady) and not ModelCheckReported then
  begin
    WizardForm.ReadyMemo.Lines.Add('');
    if ExistingModelsDetected() then
      WizardForm.ReadyMemo.Lines.Add(
        'Local models detected. First launch will verify and reuse them; no duplicate download is needed.')
    else
      WizardForm.ReadyMemo.Lines.Add(
        'No complete local model pack was detected. First launch can scan another folder or download it.');
    ModelCheckReported := True;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  RemoveModelsOnUninstall :=
    MsgBox(
      '是否同时删除 LinguaRelay 的本地模型？' + #13#10 + #13#10 +
      '选择“是”将删除约 1.36 GiB 的语音识别、翻译模型与下载缓存。' + #13#10 +
      '配置和字幕历史将继续保留。',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and RemoveModelsOnUninstall then
  begin
    DelTree(ExpandConstant('{localappdata}\LinguaRelay\models'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\LinguaRelay\downloads'), True, True, True);
  end;
end;
