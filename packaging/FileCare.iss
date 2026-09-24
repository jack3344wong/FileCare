#define MyAppNameZh "文件管家"
#define MyAppNameEn "FileCare"
#define MyAppVersion "1.3.0"
#define MyAppExeName "FileCare.exe"

[Setup]
AppId={{C72DBFB2-81A5-49E4-B32A-BBF7BFE6D9AF}
AppName={#MyAppNameZh} ({#MyAppNameEn})
AppVersion={#MyAppVersion}
AppPublisher=FileCare Contributors
AppPublisherURL=https://github.com/jack3344wong/FileCare
AppSupportURL=https://github.com/jack3344wong/FileCare/issues
AppUpdatesURL=https://github.com/jack3344wong/FileCare/releases
DefaultDirName={autopf}\FileCare
DefaultGroupName={#MyAppNameZh}
DisableProgramGroupPage=yes
OutputDir=..\installer-output
OutputBaseFilename=FileCare-Setup-{#MyAppVersion}
SetupIconFile=..\assets\filecare.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany=FileCare Contributors
VersionInfoDescription=FileCare 文件管家安装程序
VersionInfoProductName={#MyAppNameEn}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; 应用内「检查更新」会以 /SILENT 启动本安装程序，此时必须自动关闭正在运行的
; 文件管家，否则程序文件被占用会导致复制失败。RestartApplications 关掉，
; 重启改由 [Run] 段按 /UPDATE 参数执行，避免出现两个实例。
CloseApplications=yes
RestartApplications=no
; 发布目标：Windows 7 SP1 64 位及更新的 64 位 Windows。
MinVersion=6.1sp1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; 安装页内嵌动画帧：只解压到临时目录，不会留在用户电脑上。
; 放在实际程序文件之前，避免 SolidCompression 下提前解压时扫描大量数据。
Source: "..\assets\installer\frames\installer-frame-*.png"; Flags: dontcopy noencryption
Source: "..\assets\filecare.ico"; Flags: dontcopy noencryption
Source: "..\dist\FileCare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppNameZh}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{group}\卸载软件"; Filename: "{uninstallexe}"; IconFilename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppNameZh}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加选项 / Additional options:"
Name: "startmenuicon"; Description: "创建开始菜单文件夹 / Create a Start Menu folder"; GroupDescription: "附加选项 / Additional options:"

[Run]
; 应用内「检查更新」触发的静默安装（带 /UPDATE）：跳过阻塞式的首批索引，
; 安装完成后直接重新打开文件管家，索引由程序自己在后台增量构建。
Filename: "{app}\{#MyAppExeName}"; Parameters: "--build-name-index --index-budget-seconds 20"; StatusMsg: "正在建立首批文件搜索索引…"; Flags: runhidden waituntilterminated runasoriginaluser; Check: not IsUpdateInstall
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppNameZh}"; Flags: nowait postinstall skipifsilent; Check: not IsUpdateInstall
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: IsUpdateInstall

[Code]
const
  AnimationFrameCount = 60;
  AnimationInterval = 140;
  WMSetIcon = $0080;
  IconSmall = 0;
  IconBig = 1;
  ImageIcon = 1;
  LRLoadFromFile = $0010;
  LRDefaultSize = $0040;
  SMCXScreen = 0;
  SMCYScreen = 1;

var
  AnimationFrames: array of TBitmapImage;
  AnimationFrame: Integer;
  AnimationVisibleFrame: Integer;
  AnimationTimer: UINT_PTR;
  AnimationReady, AnimationMode: Boolean;
  InstallerIcon: THandle;
  NormalLeft, NormalTop, NormalWidth, NormalHeight: Integer;
  OuterLeft, OuterTop, OuterWidth, OuterHeight: Integer;
  BevelLeft, BevelTop, BevelWidth, BevelHeight: Integer;
  BackLeft, BackTop, BackWidth, BackHeight: Integer;
  NextLeft, NextTop, NextWidth, NextHeight: Integer;
  CancelLeft, CancelTop, CancelWidth, CancelHeight: Integer;
  NormalBorderStyle: TFormBorderStyle;

{ 判断本次运行是否为应用内「检查更新」触发的静默安装。
  更新流程以 /SILENT /UPDATE 启动本安装程序，此时 [Run] 段需要在安装
  结束后自动重新打开文件管家，并跳过阻塞式的首批索引构建。 }
function IsUpdateInstall: Boolean;
var
  I: Integer;
begin
  Result := False;
  if not WizardSilent then
    Exit;
  for I := 1 to ParamCount do
  begin
    if Uppercase(ParamStr(I)) = '/UPDATE' then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function SetTimer(hWnd: HWND; nIDEvent: UINT_PTR; uElapse: UINT;
  lpTimerFunc: NativeInt): UINT_PTR;
external 'SetTimer@user32.dll stdcall';

function KillTimer(hWnd: HWND; uIDEvent: UINT_PTR): BOOL;
external 'KillTimer@user32.dll stdcall';

function LoadImage(hInst: THandle; Name: String; ImageType: UINT;
  CX, CY: Integer; Flags: UINT): THandle;
external 'LoadImageW@user32.dll stdcall';

function SendMessage(hWnd: HWND; Msg: UINT; WParam: NativeUInt;
  LParam: NativeInt): NativeInt;
external 'SendMessageW@user32.dll stdcall';

function DestroyIcon(Icon: THandle): BOOL;
external 'DestroyIcon@user32.dll stdcall';

function GetSystemMetrics(Index: Integer): Integer;
external 'GetSystemMetrics@user32.dll stdcall';

procedure SetInstallerWindowIcon;
begin
  if InstallerIcon <> 0 then
  begin
    SendMessage(WizardForm.Handle, WMSetIcon, IconBig, InstallerIcon);
    SendMessage(WizardForm.Handle, WMSetIcon, IconSmall, InstallerIcon);
  end;
end;

function AnimationFramePath(FrameIndex: Integer): String;
begin
  Result := ExpandConstant('{tmp}\installer-frame-' +
    Format('%.3d', [FrameIndex]) + '.png');
end;

procedure ShowAnimationFrame(FrameIndex: Integer);
begin
  if (not AnimationReady) or (FrameIndex < 0) or
     (FrameIndex >= AnimationFrameCount) then
    Exit;

  { 所有帧已在进入安装页前解码；此处只切换内存图像，避免安装解压时掉帧。 }
  if AnimationVisibleFrame >= 0 then
    AnimationFrames[AnimationVisibleFrame].Visible := False;
  AnimationFrames[FrameIndex].BringToFront;
  AnimationFrames[FrameIndex].Visible := AnimationMode;
  AnimationVisibleFrame := FrameIndex;
end;

procedure AnimationTimerProc(Arg1: HWND; Arg2: UINT;
  Arg3: UINT_PTR; Arg4: DWORD);
begin
  if WizardForm.CurPageID = wpInstalling then
  begin
    AnimationFrame := (AnimationFrame + 1) mod AnimationFrameCount;
    ShowAnimationFrame(AnimationFrame);
  end;
end;

procedure StartAnimation;
begin
  if (not AnimationReady) or (AnimationTimer <> 0) then
    Exit;
  AnimationTimer := SetTimer(0, 0, AnimationInterval,
    CreateCallback(@AnimationTimerProc));
end;

procedure StopAnimation;
begin
  if AnimationTimer <> 0 then
  begin
    KillTimer(0, AnimationTimer);
    AnimationTimer := 0;
  end;
end;

procedure LayoutAnimation;
var
  CardWidth, CardHeight, CardLeft, CardTop: Integer;
begin
  CardWidth := ScaleX(640);
  CardHeight := (CardWidth * 9) div 16;
  CardLeft := (GetSystemMetrics(SMCXScreen) - CardWidth) div 2;
  CardTop := (GetSystemMetrics(SMCYScreen) - CardHeight) div 2;

  WizardForm.BorderStyle := bsNone;
  WizardForm.SetBounds(CardLeft, CardTop, CardWidth, CardHeight);
  WizardForm.Color := clWhite;
  for CardWidth := 0 to AnimationFrameCount - 1 do
    AnimationFrames[CardWidth].SetBounds(
      0, 0, WizardForm.ClientWidth, WizardForm.ClientHeight);
  SetInstallerWindowIcon;
end;

procedure EnterAnimationMode;
begin
  if AnimationMode or (not AnimationReady) then
    Exit;
  AnimationMode := True;

  { 保留同一个安装窗口和任务栏按钮，仅把向导控件移出可视区。 }
  WizardForm.OuterNotebook.Left := -10000;
  WizardForm.Bevel.Left := -10000;
  WizardForm.BackButton.Left := -10000;
  WizardForm.NextButton.Left := -10000;
  WizardForm.CancelButton.Left := -10000;
  LayoutAnimation;
  ShowAnimationFrame(AnimationFrame);
  StartAnimation;
end;

procedure LeaveAnimationMode;
begin
  if not AnimationMode then
    Exit;
  StopAnimation;
  AnimationMode := False;
  if AnimationVisibleFrame >= 0 then
    AnimationFrames[AnimationVisibleFrame].Visible := False;

  WizardForm.BorderStyle := NormalBorderStyle;
  WizardForm.SetBounds(NormalLeft, NormalTop, NormalWidth, NormalHeight);
  WizardForm.OuterNotebook.SetBounds(OuterLeft, OuterTop, OuterWidth, OuterHeight);
  WizardForm.Bevel.SetBounds(BevelLeft, BevelTop, BevelWidth, BevelHeight);
  WizardForm.BackButton.SetBounds(BackLeft, BackTop, BackWidth, BackHeight);
  WizardForm.NextButton.SetBounds(NextLeft, NextTop, NextWidth, NextHeight);
  WizardForm.CancelButton.SetBounds(CancelLeft, CancelTop, CancelWidth, CancelHeight);
  SetInstallerWindowIcon;
end;

procedure InitializeWizard;
begin
  AnimationTimer := 0;
  AnimationFrame := 0;
  AnimationReady := False;
  AnimationMode := False;
  AnimationVisibleFrame := -1;
  InstallerIcon := 0;

  NormalLeft := WizardForm.Left;
  NormalTop := WizardForm.Top;
  NormalWidth := WizardForm.Width;
  NormalHeight := WizardForm.Height;
  NormalBorderStyle := WizardForm.BorderStyle;
  OuterLeft := WizardForm.OuterNotebook.Left;
  OuterTop := WizardForm.OuterNotebook.Top;
  OuterWidth := WizardForm.OuterNotebook.Width;
  OuterHeight := WizardForm.OuterNotebook.Height;
  BevelLeft := WizardForm.Bevel.Left;
  BevelTop := WizardForm.Bevel.Top;
  BevelWidth := WizardForm.Bevel.Width;
  BevelHeight := WizardForm.Bevel.Height;
  BackLeft := WizardForm.BackButton.Left;
  BackTop := WizardForm.BackButton.Top;
  BackWidth := WizardForm.BackButton.Width;
  BackHeight := WizardForm.BackButton.Height;
  NextLeft := WizardForm.NextButton.Left;
  NextTop := WizardForm.NextButton.Top;
  NextWidth := WizardForm.NextButton.Width;
  NextHeight := WizardForm.NextButton.Height;
  CancelLeft := WizardForm.CancelButton.Left;
  CancelTop := WizardForm.CancelButton.Top;
  CancelWidth := WizardForm.CancelButton.Width;
  CancelHeight := WizardForm.CancelButton.Height;

  if WizardSilent then
    Exit;

  ExtractTemporaryFiles('{tmp}\installer-frame-*.png');
  ExtractTemporaryFile('filecare.ico');
  InstallerIcon := LoadImage(0, ExpandConstant('{tmp}\filecare.ico'),
    ImageIcon, 0, 0, LRLoadFromFile or LRDefaultSize);
  SetInstallerWindowIcon;

  { 预载并解码全部帧。安装时只改变可见性，避免每帧磁盘读取造成卡顿。 }
  SetArrayLength(AnimationFrames, AnimationFrameCount);
  for AnimationFrame := 0 to AnimationFrameCount - 1 do
  begin
    AnimationFrames[AnimationFrame] := TBitmapImage.Create(WizardForm);
    AnimationFrames[AnimationFrame].Parent := WizardForm;
    AnimationFrames[AnimationFrame].Stretch := True;
    AnimationFrames[AnimationFrame].Center := True;
    AnimationFrames[AnimationFrame].Visible := False;
    AnimationFrames[AnimationFrame].PngImage.LoadFromFile(
      AnimationFramePath(AnimationFrame));
  end;
  AnimationFrame := 0;
  AnimationReady := True;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpInstalling then
  begin
    if AnimationReady then
      EnterAnimationMode;
  end
  else
    LeaveAnimationMode;
end;

procedure DeinitializeSetup;
begin
  StopAnimation;
  if InstallerIcon <> 0 then
    DestroyIcon(InstallerIcon);
end;

// ========== 卸载前关闭运行中的程序 ==========
// 在删除文件前先尝试关闭正在运行的程序实例
// 使用两阶段策略：先尝试优雅关闭（通过本地 socket），失败则强制结束

var
  DeleteUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  // 在卸载开始时询问是否删除用户数据
  DeleteUserData := MsgBox(
    '是否同时删除用户数据？' + #13#10 + #13#10 +
    '用户数据包括：' + #13#10 +
    '  • 文件索引数据库（约 9GB）' + #13#10 +
    '  • 全文搜索索引' + #13#10 +
    '  • 回收站缓存' + #13#10 +
    '  • 用户配置文件' + #13#10 + #13#10 +
    '选择“是”将完全清除所有数据，选择“否”将保留数据以便重新安装后复用。',
    '删除用户数据',
    // Inno Setup 7 移除了全部 MB_ICON* 常量；带自定义标题的 MsgBox 重载
    // 本身不接受图标类型参数，因此这里只保留标题 + 按钮。
    MB_YESNO
  ) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  RetryCount: Integer;
  ProcessFound: Boolean;
  UserDataDir: String;
begin
  // 在删除文件之前（usUninstall 阶段）关闭运行中的程序
  if CurUninstallStep = usUninstall then
  begin
    // 第一阶段：尝试通过 tasklist 检测进程是否存在
    ResultCode := 0;
    if not Exec('tasklist', '/FI "IMAGENAME eq FileCare.exe" /NH', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      // 如果无法执行 tasklist，直接尝试 taskkill
      Exec('taskkill', '/F /IM FileCare.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Sleep(500);
    end
    else
    begin
      // 检查 tasklist 输出中是否包含 FileCare.exe
      // 由于无法直接读取输出，使用 findstr 进行过滤
      if Exec('tasklist', '/FI "IMAGENAME eq FileCare.exe" /NH | findstr /I "FileCare.exe"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      begin
        // 进程存在，强制结束进程
        Exec('taskkill', '/F /IM FileCare.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        
        // 等待进程完全退出（最多 3 秒）
        RetryCount := 0;
        while (RetryCount < 30) do
        begin
          Sleep(100);
          // 检查进程是否还在运行
          if not Exec('tasklist', '/FI "IMAGENAME eq FileCare.exe" /NH | findstr /I "FileCare.exe"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
          begin
            // findstr 返回非零表示进程已退出
            Break;
          end;
          Inc(RetryCount);
        end;
        
        // 如果 3 秒后进程仍在运行，提示用户
        if RetryCount >= 30 then
        begin
          MsgBox('文件管家无法自动关闭。请手动关闭程序后重试卸载。', mbError, MB_OK);
          Abort;
        end;
      end;
    end;
    
    // 额外等待确保文件句柄释放
    Sleep(500);
  end;
  
  // 在卸载完成后（usPostUninstall 阶段）删除用户数据
  if CurUninstallStep = usPostUninstall then
  begin
    // 清理开机自启动注册表项
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FileCare');
    
    if DeleteUserData then
    begin
      UserDataDir := ExpandConstant('{%USERPROFILE}\.diskwise');
      if DirExists(UserDataDir) then
      begin
        if not DelTree(UserDataDir, True, True, True) then
        begin
          MsgBox('无法完全删除用户数据目录，部分文件可能正在被使用。' + #13#10 +
                 '请手动删除：' + UserDataDir, mbInformation, MB_OK);
        end;
      end;
    end;
  end;
end;

