; KPL 赛训工具 —— Windows 安装程序（Inno Setup 6）
;
; 由 scripts/make_installer.py 调用，参数示例：
;   ISCC.exe /Qp /DAppVersion=1.0.0 /DAppVersion4=1.0.0.0 ^
;            /DSourceDir="...\dist\_installer" /DOutputDir="...\dist" installer.iss
;
; 安装到 %LOCALAPPDATA%\KPL赛训工具，不需要管理员权限；
; 卸载时保留 data 目录，避免误删比赛数据。

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppVersion4
  #define AppVersion4 AppVersion + ".0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\_installer"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
; 工作台端口：升级/卸载前用它探测并停止正在运行的实例。
#ifndef AppPort
  #define AppPort "8766"
#endif

#define AppName "KPL 赛训工具"
#define AppShortName "KPL赛训工具"
; 产出文件名用 ASCII（下载/CI/网盘都更稳），安装目录仍用 AppShortName，避免老用户升级后找不到 data/
#define AppFileName "KPL-Scrim-Lab"
; 双击入口：PyInstaller 打包的薄壳启动器，内部再调 runtime\pythonw.exe launcher.py
#define AppExe "KPLScrimLab.exe"
#define AppPublisher "KPL 赛训工具"
#define AppURL "https://github.com/hccccc01333/kpl-scrim-lab"

[Setup]
AppId={{6F1C2D84-9A3B-4E57-8C21-5B7E9D0A4F13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename={#AppFileName}-{#AppVersion}-setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\app.ico
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=yes
AllowNoIcons=yes
VersionInfoVersion={#AppVersion4}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion4}
SetupMutex=KPLScrimLabSetupMutex
MinVersion=10.0

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机时后台启动工作台（不弹浏览器）"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Comment: "打开赛训数据工作台"
Name: "{group}\停止工作台"; Filename: "{app}\{#AppExe}"; Parameters: "--stop"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Comment: "停止后台服务"
Name: "{group}\检查更新"; Filename: "{app}\检查更新.bat"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Comment: "检查并查看更新说明"
Name: "{group}\打开数据目录"; Filename: "{app}\data"; IconFilename: "{app}\app.ico"; Comment: "比赛数据、授权与备份都在这里"
Name: "{group}\打开日志目录"; Filename: "{app}\logs"; IconFilename: "{app}\app.ico"; Comment: "启动失败或界面异常时，把这里的文件发给支持人员"
Name: "{group}\使用说明"; Filename: "{app}\部署说明.txt"; IconFilename: "{app}\app.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "KPLScrimLab"; ValueData: """{app}\runtime\pythonw.exe"" ""{app}\launcher.py"" --autostart"; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
; 程序文件由安装器记录并删除；这里只清理运行期生成、且不属于用户数据的内容。
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\v3\__pycache__"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\data\update"
; data 目录（比赛数据、授权、备份）故意保留。

[Code]
const
  AppHealthUrl = 'http://127.0.0.1:{#AppPort}/api/health';
  AppShutdownUrl = 'http://127.0.0.1:{#AppPort}/api/shutdown';

function HttpSend(Method, Url, Body: String; var StatusCode: Integer;
  var ResponseText: String): Boolean;
var
  Http: Variant;
begin
  Result := False;
  StatusCode := 0;
  ResponseText := '';
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open(Method, Url, False);
    Http.SetTimeouts(800, 800, 800, 800);
    if Method = 'POST' then
      Http.SetRequestHeader('Content-Type', 'application/json');
    Http.Send(Body);
    StatusCode := Http.Status;
    ResponseText := Http.ResponseText;
    Result := True;
  except
    Result := False;
  end;
end;

function RunningPid(): Integer;
var
  StatusCode, P, I, StartPos: Integer;
  Text, Digits: String;
begin
  Result := 0;
  if not HttpSend('GET', AppHealthUrl, '', StatusCode, Text) then
    Exit;
  if StatusCode <> 200 then
    Exit;
  P := Pos('"pid":', Text);
  if P = 0 then
    Exit;
  StartPos := P + 6;
  Digits := '';
  for I := StartPos to Length(Text) do
  begin
    if (Text[I] >= '0') and (Text[I] <= '9') then
      Digits := Digits + Text[I]
    else if Digits <> '' then
      Break;
  end;
  Result := StrToIntDef(Digits, 0);
end;

function StopRunningApp(): Boolean;
var
  Pid, I, StatusCode: Integer;
  Text: String;
  ResultCode: Integer;
begin
  Pid := RunningPid();
  if Pid = 0 then
  begin
    Result := True;
    Exit;
  end;

  { 1) 优雅停止：走 /api/shutdown，等进程自己退出。 }
  HttpSend('POST', AppShutdownUrl, '{}', StatusCode, Text);
  for I := 1 to 24 do
  begin
    Sleep(250);
    if RunningPid() = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;

  { 2) 兜底：结束进程。 }
  Exec(ExpandConstant('{sys}\taskkill.exe'),
       '/PID ' + IntToStr(Pid) + ' /F', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
  Result := RunningPid() = 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not StopRunningApp() then
    Result := '检测到工作台仍在运行，为避免覆盖正在使用的文件，安装已暂停。' +
              Chr(13) + Chr(10) + Chr(13) + Chr(10) +
              '请从开始菜单打开「停止工作台」，或重启电脑后再运行安装程序。' +
              Chr(13) + Chr(10) +
              '如果 {#AppPort} 端口被其他程序占用，请先关闭那个程序。';
end;

{ 逐段比较 1.4.0 vs 1.3.9 这类版本号；返回 1 / 0 / -1。 }
function CompareVersionStr(A, B: String): Integer;
var
  I, P, NA, NB: Integer;
  SA, SB: String;
begin
  Result := 0;
  for I := 1 to 4 do
  begin
    P := Pos('.', A);
    if P > 0 then
    begin
      SA := Copy(A, 1, P - 1);
      A := Copy(A, P + 1, Length(A));
    end
    else
    begin
      SA := A;
      A := '';
    end;
    P := Pos('.', B);
    if P > 0 then
    begin
      SB := Copy(B, 1, P - 1);
      B := Copy(B, P + 1, Length(B));
    end
    else
    begin
      SB := B;
      B := '';
    end;
    NA := StrToIntDef(SA, 0);
    NB := StrToIntDef(SB, 0);
    if NA > NB then
    begin
      Result := 1;
      Exit;
    end;
    if NA < NB then
    begin
      Result := -1;
      Exit;
    end;
  end;
end;

{ 防降级：已经装了更新的版本时，双击旧安装包会静默回退，赛训组很难自己发现。 }
function InitializeSetup(): Boolean;
var
  Installed, Key: String;
begin
  Result := True;
  { 花括号在 Inno 的 Pascal 里会被当成常量引用，所以用 Chr 拼出来。 }
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\';
  Key := Key + Chr(123) + '6F1C2D84-9A3B-4E57-8C21-5B7E9D0A4F13' + Chr(125) + '_is1';
  if not RegQueryStringValue(HKCU, Key, 'DisplayVersion', Installed) then
  begin
    Log('降级检查: 未读到已安装版本，按全新安装处理');
    Exit;
  end;
  Log('降级检查: 已安装=' + Installed + ' 本包={#AppVersion}');
  if Installed = '' then
    Exit;
  if CompareVersionStr('{#AppVersion}', Installed) >= 0 then
    Exit;

  if WizardSilent then
  begin
    { 静默安装不做降级，直接中止，避免脚本误装旧版。 }
    Result := False;
    Exit;
  end;

  Result := MsgBox('这台电脑已经装了更新的版本 ' + Installed + '。' + Chr(13) + Chr(10) +
                   '当前安装包是 {#AppVersion}，继续安装会把程序降级。' +
                   Chr(13) + Chr(10) + Chr(13) + Chr(10) +
                   '比赛数据不会丢，但界面和功能会退回旧版。确实要降级吗？',
                   mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRunningApp();
  if CurUninstallStep = usPostUninstall then
    if not UninstallSilent then
      MsgBox('程序文件已删除。' + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
             '安装目录下的 data 文件夹已保留，里面是全部比赛数据、营地授权和备份。' +
             Chr(13) + Chr(10) + '确认不再需要时，可手动删除整个安装目录。',
             mbInformation, MB_OK);
end;
