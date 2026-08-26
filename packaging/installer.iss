#ifndef AppVersion
  #define AppVersion "0.3.1"
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
InfoBeforeFile=..\docs\INSTALL.zh-CN.txt
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
  RemoveUserDataOnUninstall: Boolean;

function ExistingModelsDetected(): Boolean;
var
  ModelRoot: String;
begin
  ModelRoot := ExpandConstant('{localappdata}\LinguaRelay\models');
  Result :=
    (FileExists(ModelRoot + '\models--Systran--faster-whisper-small\snapshots\536b0662742c02347bc0e980a01041f333bce120\model.bin') or
     FileExists(ModelRoot + '\models--Systran--faster-whisper-base\snapshots\ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66\model.bin')) and
    FileExists(ModelRoot + '\m2m100_418m_ct2\model.bin');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpReady) and not ModelCheckReported then
  begin
    WizardForm.ReadyMemo.Lines.Add('');
    if ExistingModelsDetected() then
      WizardForm.ReadyMemo.Lines.Add(
        '已检测到本地模型。首次启动会校验并直接复用，不会重复下载。')
    else
      WizardForm.ReadyMemo.Lines.Add(
        '未检测到完整模型。首次启动可安装 Small/Base 基础包；之后可选择 Medium、Large-v3 Turbo、Large-v3 或 M2M100 1.2B。');
    ModelCheckReported := True;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  RemoveModelsOnUninstall :=
    MsgBox(
      '是否同时删除 LinguaRelay 的本地模型？' + #13#10 + #13#10 +
      '选择“是”将删除已安装的语音识别、翻译模型与下载缓存。' + #13#10 +
      '配置和字幕历史将继续保留。',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) = IDYES;
  RemoveUserDataOnUninstall :=
    MsgBox(
      '是否同时删除录音、离线项目、配置和字幕历史？' + #13#10 + #13#10 +
      '这些用户数据可能包含私密音频。选择“否”可在重新安装后继续使用。',
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
  if (CurUninstallStep = usUninstall) and RemoveUserDataOnUninstall then
  begin
    DelTree(ExpandConstant('{localappdata}\LinguaRelay\projects'), True, True, True);
    DeleteFile(ExpandConstant('{localappdata}\LinguaRelay\config.toml'));
    DeleteFile(ExpandConstant('{localappdata}\LinguaRelay\history.jsonl'));
    DeleteFile(ExpandConstant('{localappdata}\LinguaRelay\glossary.json'));
  end;
end;
