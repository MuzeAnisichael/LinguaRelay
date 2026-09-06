#ifndef AppVersion
  #define AppVersion "0.3.3"
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

#ifdef SmokeTest
  #define AppName "LinguaRelay Installer Smoke Test"
  #if ModelPackDir != ""
    #error SmokeTest must not install model packs into a user data directory.
  #endif
#else
  #define AppName "LinguaRelay"
#endif
#define AppPublisher "Leeleelee"
#define AppURL "https://github.com/MuzeAnisichael/LinguaRelay"
#define AppExeName "LinguaRelay.exe"

[Setup]
#ifdef SmokeTest
AppId={{92733A95-3A79-4A10-848B-7EC0C316AD51}
CreateUninstallRegKey=no
UninstallDisplayName=LinguaRelay Installer Smoke Test
VersionInfoProductName=LinguaRelay Installer Smoke Test
DefaultDirName={tmp}\LinguaRelay-Installer-Smoke
OutputBaseFilename=LinguaRelay-{#AppVersion}-Smoke-Setup-x64
CloseApplications=no
#else
AppId={{B40F672E-4591-43D6-8657-4D4A71F337E5}
DefaultDirName={localappdata}\Programs\{#AppName}
OutputBaseFilename=LinguaRelay-{#AppVersion}-Setup-x64
CloseApplications=yes
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoBeforeFile=..\docs\INSTALL.zh-CN.txt
OutputDir={#OutputDir}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
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
Source: "{#ModelPackDir}\*"; DestDir: "{localappdata}\LinguaRelay\models"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall
#endif

[InstallDelete]
; Remove incompatible DLLs accidentally shipped by v0.3.0 before an in-place upgrade.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icuin.dll"
Type: files; Name: "{app}\_internal\icudt78.dll"
Type: files; Name: "{app}\_internal\libcrypto-3-x64.dll"
Type: files; Name: "{app}\_internal\libssl-3-x64.dll"
; These optional Qt plugins/dependencies were shipped by v0.3.2. Match exact
; application-owned paths; never recursively clean the user's installation dir.
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qpdf.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6Pdf.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6VirtualKeyboard.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6Quick.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6Qml.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6QmlMeta.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6QmlModels.dll"
Type: files; Name: "{app}\_internal\PySide6\Qt6QmlWorkerScript.dll"

#ifndef SmokeTest
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
#endif

; Inno's file log removes installed application files. Do not use an
; [UninstallDelete] wildcard: users may keep models or exports beside the EXE.

[Code]
var
  ModelCheckReported: Boolean;
  RemoveModelsOnUninstall: Boolean;
  RemoveUserDataOnUninstall: Boolean;

function ExistingModelLocations(): String;
var
  Candidates: TArrayOfString;
  Index: Integer;
begin
  Result := '';
  SetArrayLength(Candidates, 4);
  Candidates[0] := GetEnv('LINGUA_RELAY_MODEL_DIR');
  Candidates[1] := ExpandConstant('{localappdata}\LinguaRelay\models');
  Candidates[2] := ExpandConstant('{app}\models');
  if GetEnv('USERPROFILE') <> '' then
    Candidates[3] := GetEnv('USERPROFILE') + '\LinguaRelay\models';
  for Index := 0 to 3 do
    if (Candidates[Index] <> '') and DirExists(Candidates[Index]) then
      Result := Result + #13#10 + '  ' + Candidates[Index];
end;

procedure CurPageChanged(CurPageID: Integer);
var
  ModelLocations: String;
begin
  if (CurPageID = wpReady) and not ModelCheckReported then
  begin
    WizardForm.ReadyMemo.Lines.Add('');
    ModelLocations := ExistingModelLocations();
    if ModelLocations <> '' then
      WizardForm.ReadyMemo.Lines.Add(
        '发现可能的本地模型目录：' + ModelLocations + #13#10 +
        '安装程序仅检查目录是否存在。首次启动会校验模型完整性，已验证的模型可直接复用。')
    else
      WizardForm.ReadyMemo.Lines.Add(
        '常用位置中未发现模型目录。首次启动可选择其它已有目录或安装 Small/Base 基础包；之后可选择更高质量模型。');
    ModelCheckReported := True;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  RemoveModelsOnUninstall := False;
  RemoveUserDataOnUninstall := False;
  Result := True;
#ifdef SmokeTest
  Exit;
#else
  if UninstallSilent then
    Exit;
  RemoveModelsOnUninstall :=
    MsgBox(
      '是否同时删除 LinguaRelay 的本地模型？' + #13#10 + #13#10 +
      '选择“是”将删除默认数据目录中的模型与下载缓存：' + #13#10 +
      ExpandConstant('{localappdata}\LinguaRelay') + #13#10 +
      '其它位置和程序目录中自行放入的模型不会删除。配置和字幕历史将继续保留。',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) = IDYES;
  RemoveUserDataOnUninstall :=
    MsgBox(
      '是否同时删除录音、离线项目、配置和字幕历史？' + #13#10 + #13#10 +
      '这些用户数据可能包含私密音频。选择“否”可在重新安装后继续使用。',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) = IDYES;
#endif
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
#ifndef SmokeTest
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
#endif
end;
