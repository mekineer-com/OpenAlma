#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif

#define MyAppName "OpenAlma"
#define MyAppPublisher "OpenAlma"
#define MyAppURL "https://openalma.org"

[Setup]
AppId={{41D67BBF-3DC6-45AC-962B-CFE0356E7245}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
SetupIconFile=OpenAlma.ico
DefaultDirName={localappdata}\Programs\OpenAlma
DefaultGroupName=OpenAlma
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=output
OutputBaseFilename=OpenAlma-{#MyAppVersion}-Windows
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=OpenAlma Launcher
UninstallDisplayIcon={app}\OpenAlma.ico

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\..\launcher\windows_stop.py"; Flags: dontcopy
Source: "..\..\launcher\*"; DestDir: "{app}\launcher"; Excludes: ".venv\*,__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\docs\favicon.svg"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\release-components.json"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: PrepareLauncher
Source: "OpenAlma.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OpenAlma"; Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; WorkingDir: "{app}\launcher"; IconFilename: "{app}\OpenAlma.ico"
Name: "{autodesktop}\OpenAlma"; Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; WorkingDir: "{app}\launcher"; IconFilename: "{app}\OpenAlma.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; Description: "Launch OpenAlma"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\launcher\.venv"
Type: filesandordirs; Name: "{app}\launcher\__pycache__"
Type: files; Name: "{app}\.openalma-version"

[Code]
const
  PythonInstallerName = 'python-3.12.10-amd64.exe';
  PythonInstallerUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe';
  PythonInstallerSHA256 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb';

var
  PythonLauncher: String;
  RemoveEverything: Boolean;
  ServicesVerified: Boolean;
  LastLauncherCheckCode: Integer;

function FindOnPath(const Filename: String): String;
begin
  Result := FileSearch(Filename, GetEnv('PATH'));
end;

function FindPythonLauncher(): String;
begin
  Result := FindOnPath('py.exe');
  if (Result = '') and FileExists(ExpandConstant('{localappdata}\Programs\Python\Launcher\py.exe')) then
    Result := ExpandConstant('{localappdata}\Programs\Python\Launcher\py.exe');
  if (Result = '') and FileExists(ExpandConstant('{win}\py.exe')) then
    Result := ExpandConstant('{win}\py.exe');
end;

function FindGit(): String;
begin
  Result := FindOnPath('git.exe');
  if (Result = '') and FileExists(ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe')) then
    Result := ExpandConstant('{localappdata}\Programs\Git\cmd\git.exe');
  if (Result = '') and FileExists(ExpandConstant('{pf64}\Git\cmd\git.exe')) then
    Result := ExpandConstant('{pf64}\Git\cmd\git.exe');
  if (Result = '') and FileExists(ExpandConstant('{pf32}\Git\cmd\git.exe')) then
    Result := ExpandConstant('{pf32}\Git\cmd\git.exe');
end;

function FindWinget(): String;
begin
  Result := FindOnPath('winget.exe');
  if (Result = '') and FileExists(ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe')) then
    Result := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
end;

function RunHidden(const Filename, Params: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(Filename, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InstallWithWinget(const PackageId, Scope: String): Boolean;
var
  Winget, Params: String;
  ResultCode: Integer;
begin
  Winget := FindWinget();
  if Winget = '' then
  begin
    MsgBox('Windows Package Manager (winget) is required to install missing prerequisites.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Params := 'install --id ' + PackageId + ' -e --accept-package-agreements --accept-source-agreements';
  if Scope <> '' then
    Params := Params + ' --scope ' + Scope;
  WizardForm.StatusLabel.Caption := 'Installing ' + PackageId + '...';
  Result := RunHidden(Winget, Params, ResultCode) and (ResultCode = 0);
end;

function EnsurePrerequisites(): String;
var
  ResultCode: Integer;
begin
  Result := '';
  LastLauncherCheckCode := 0;
  ResultCode := -1;
  PythonLauncher := FindPythonLauncher();
  if (PythonLauncher = '') or not RunHidden(PythonLauncher, '-3.12 --version', ResultCode) or (ResultCode <> 0) then
  begin
    if MsgBox('OpenAlma requires Python 3.12. Install it now?', mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := 'Python 3.12 is required.';
      Exit;
    end;
    WizardForm.StatusLabel.Caption := 'Downloading Python 3.12...';
    try
      DownloadTemporaryFile(PythonInstallerUrl, PythonInstallerName, PythonInstallerSHA256, nil);
    except
      Log('Python download or verification failed: ' + GetExceptionMessage);
      Result := 'Could not download and verify Python 3.12. Reconnect and try again.'#13#10 +
        'Or install it from ' + PythonInstallerUrl + ' and run OpenAlma Setup again.';
      Exit;
    end;
    WizardForm.StatusLabel.Caption := 'Installing Python 3.12 for your account...';
    if not RunHidden(
      ExpandConstant('{tmp}\') + PythonInstallerName,
      '/quiet /norestart InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0',
      ResultCode
    ) or (ResultCode <> 0) then
    begin
      Log(Format('Python installer exited with code %d.', [ResultCode]));
      if ResultCode = 3010 then
        Result := 'Python 3.12 was installed. Restart Windows, then run OpenAlma Setup again.'
      else
        Result := 'Python 3.12 installation failed. Install it from ' + PythonInstallerUrl +
          ' and run OpenAlma Setup again.';
      Exit;
    end;
    PythonLauncher := FindPythonLauncher();
    if (PythonLauncher = '') or not RunHidden(PythonLauncher, '-3.12 --version', ResultCode) or (ResultCode <> 0) then
    begin
      Result := 'Python 3.12 could not be verified. Install it from ' + PythonInstallerUrl +
        ' with Python Launcher enabled, then run OpenAlma Setup again.';
      Exit;
    end;
  end;

  if FindGit() = '' then
  begin
    if MsgBox('OpenAlma requires Git to install its components. Install it now?', mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := 'Git is required.';
      Exit;
    end;
    if not InstallWithWinget('Git.Git', 'user') and not InstallWithWinget('Git.Git', '') then
    begin
      Result := 'Git installation failed.';
      Exit;
    end;
    if FindGit() = '' then
    begin
      Result := 'Git was installed but could not be found.';
      Exit;
    end;
  end;
end;

function StopInstalledLauncher(RequireUpdateReady: Boolean): String;
var
  Python, Script, Argument: String;
  ResultCode: Integer;
begin
  Result := '';
  Python := ExpandConstant('{app}\launcher\.venv\Scripts\pythonw.exe');
  Script := ExpandConstant('{app}\launcher\windows_start.pyw');
  if not FileExists(Python) then
    Python := PythonLauncher;
  if RequireUpdateReady then
    Argument := '--prepare-update'
  else
    Argument := '--stop-existing';
  if (Python <> '') and FileExists(Python) and FileExists(Script) then
    if not RunHidden(Python, '"' + Script + '" ' + Argument, ResultCode) or (ResultCode <> 0) then
    begin
      LastLauncherCheckCode := ResultCode;
      if ResultCode = 11 then
        Result := 'Stop every OpenAlma service and wait for any installation to finish, then click Retry.'
      else
        Result := 'OpenAlma could not verify that all services are stopped.';
    end;
end;

function StopAnyLauncher(RequireUpdateReady: Boolean): String;
var
  Helper, Params: String;
  ResultCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('windows_stop.py');
  Helper := ExpandConstant('{tmp}\windows_stop.py');
  Params := '-3.12 "' + Helper + '" --install-dir "' + ExpandConstant('{app}') + '"';
  if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{41D67BBF-3DC6-45AC-962B-CFE0356E7245}_is1') then
    Params := Params + ' --registered-install';
  if RequireUpdateReady then
    Params := Params + ' --require-update-ready';
  if not RunHidden(PythonLauncher, Params, ResultCode) then
    Result := 'Could not check the running OpenAlma Launcher.'
  else if ResultCode = 11 then
    Result := 'Stop all OpenAlma services and wait for any installation to finish, then click Retry.'
  else if ResultCode = 12 then
    Result := 'Port 8765 is occupied by a process that is not a verified OpenAlma Launcher.'
  else if ResultCode = 13 then
    Result := 'OpenAlma Launcher did not exit. Use Exit in OpenAlma, then click Retry.'
  else if ResultCode = 14 then
    Result := 'OpenAlma launcher files are incomplete, so running services cannot be verified.'
  else if ResultCode <> 0 then
    Result := 'Could not stop OpenAlma Launcher.';
end;

function CheckInstalledRelease(var IsUpgrade: Boolean): String;
var
  Python, Helper, AppsRoot: String;
  ResultCode: Integer;
begin
  Result := '';
  IsUpgrade := False;
  Python := ExpandConstant('{app}\launcher\.venv\Scripts\python.exe');
  Helper := ExpandConstant('{app}\launcher\windows_install.py');
  AppsRoot := ExpandConstant('{localappdata}\OpenAlma');
  if FileExists(Python) and FileExists(Helper) then
  begin
    if not RunHidden(
      Python,
      '"' + Helper + '" --apps-root "' + AppsRoot + '" --release-tag "{#MyAppVersion}" --compare-release',
      ResultCode
    ) then
      Result := 'Could not verify the installed OpenAlma release.'
    else if ResultCode = 10 then
      IsUpgrade := True
    else if ResultCode = 2 then
      Result := 'This installer is older than the installed OpenAlma release.'
    else if ResultCode = 3 then
      Result := 'The installed OpenAlma release metadata is damaged or conflicts with this installer.'
    else if ResultCode <> 0 then
      Result := 'Could not verify the installed OpenAlma release.';
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  IsUpgrade: Boolean;
begin
  Result := EnsurePrerequisites();
  if Result = '' then
    Result := CheckInstalledRelease(IsUpgrade);
  if (Result = '') and IsUpgrade then
    if MsgBox(
      'OpenAlma Launcher updates first. Installed services will show Update required and cannot start until their matching updates complete.'#13#10#13#10 +
      'Your settings and soul data are preserved. Continue?',
      mbConfirmation, MB_YESNO
    ) <> IDYES then
      Result := 'Update cancelled.';
  if Result = '' then
    Result := StopInstalledLauncher(True);
  if Result = '' then
    Result := StopAnyLauncher(True);
end;

procedure RunChecked(const Filename, Params, Failure: String);
var
  ResultCode: Integer;
begin
  if not RunHidden(Filename, Params, ResultCode) or (ResultCode <> 0) then
    RaiseException(Failure);
end;

procedure PrepareLauncher();
var
  VenvPython, LauncherDir, AppsRoot: String;
begin
  LauncherDir := ExpandConstant('{app}\launcher');
  AppsRoot := ExpandConstant('{localappdata}\OpenAlma');
  WizardForm.StatusLabel.Caption := 'Creating the OpenAlma Python environment...';
  RunChecked(PythonLauncher, '-3.12 -m venv "' + LauncherDir + '\.venv"', 'Could not create the OpenAlma Python environment.');
  VenvPython := LauncherDir + '\.venv\Scripts\python.exe';
  WizardForm.StatusLabel.Caption := 'Installing OpenAlma launcher dependencies...';
  RunChecked(VenvPython, '-m pip install --disable-pip-version-check -r "' + LauncherDir + '\requirements.txt"', 'Could not install OpenAlma launcher dependencies.');
  WizardForm.StatusLabel.Caption := 'Configuring OpenAlma...';
  RunChecked(
    VenvPython,
    '"' + LauncherDir + '\windows_install.py" --apps-root "' + AppsRoot + '" --release-tag "{#MyAppVersion}"',
    'Could not configure the OpenAlma Apps root.'
  );
end;

function InitializeUninstall(): Boolean;
var
  Python, Script: String;
begin
  PythonLauncher := FindPythonLauncher();
  Python := ExpandConstant('{app}\launcher\.venv\Scripts\pythonw.exe');
  Script := ExpandConstant('{app}\launcher\windows_start.pyw');
  ServicesVerified := FileExists(Python) and FileExists(Script);
  if not ServicesVerified then
  begin
    MsgBox(
      'OpenAlma cannot verify running services because its launcher files are incomplete.'#13#10#13#10 +
      'Normal uninstall may continue and will preserve components and data. Remove Everything will be unavailable.',
      mbInformation, MB_OK
    );
    Result := True;
    Exit;
  end;
  Result := StopInstalledLauncher(True) = '';
  ServicesVerified := Result;
  if not Result then
  begin
    if LastLauncherCheckCode = 11 then
      MsgBox('Open OpenAlma, stop every service and wait for any installation to finish, then retry uninstall.', mbError, MB_OK)
    else begin
      ServicesVerified := False;
      MsgBox(
        'OpenAlma could not verify running services because its launcher is damaged.'#13#10#13#10 +
        'Normal uninstall may continue and will preserve components and data. Remove Everything will be unavailable.',
        mbInformation, MB_OK
      );
      Result := True;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Python, Script: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveEverything := False;
    if ServicesVerified then
    begin
      RemoveEverything := MsgBox(
        'Keep installed components, settings, and soul data?'#13#10#13#10 +
        'Choose Yes to keep them (recommended), or No to consider removing everything.',
        mbConfirmation, MB_YESNO
      ) = IDNO;
    end;
    if RemoveEverything then
    begin
      Python := ExpandConstant('{app}\launcher\.venv\Scripts\python.exe');
      Script := ExpandConstant('{app}\launcher\windows_remove.py');
      if not RunHidden(Python, '"' + Script + '"', ResultCode) or (ResultCode <> 0) then
        RaiseException('Remove Everything could not complete. Some files may already have been deleted. Close apps using the folder before trying again.');
    end;
  end;
end;
