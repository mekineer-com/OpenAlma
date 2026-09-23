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

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\..\launcher\*"; DestDir: "{app}\launcher"; Excludes: ".venv\*,__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\docs\favicon.svg"; DestDir: "{app}\docs"; Flags: ignoreversion; AfterInstall: PrepareLauncher

[Icons]
Name: "{autoprograms}\OpenAlma"; Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; WorkingDir: "{app}\launcher"
Name: "{autodesktop}\OpenAlma"; Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; WorkingDir: "{app}\launcher"; Tasks: desktopicon

[Run]
Filename: "{app}\launcher\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher\windows_start.pyw"""; Description: "Launch OpenAlma"; Flags: nowait postinstall skipifsilent

[Code]
var
  PythonLauncher: String;
  RemoveEverything: Boolean;

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
  if (Result = '') and FileExists(ExpandConstant('{pf}\Git\cmd\git.exe')) then
    Result := ExpandConstant('{pf}\Git\cmd\git.exe');
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
  PythonLauncher := FindPythonLauncher();
  if (PythonLauncher = '') or not RunHidden(PythonLauncher, '-3.12 --version', ResultCode) or (ResultCode <> 0) then
  begin
    if MsgBox('OpenAlma requires Python 3.12. Install it now?', mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := 'Python 3.12 is required.';
      Exit;
    end;
    if not InstallWithWinget('Python.Python.3.12', 'user') then
    begin
      Result := 'Python 3.12 installation failed.';
      Exit;
    end;
    PythonLauncher := FindPythonLauncher();
    if PythonLauncher = '' then
    begin
      Result := 'Python 3.12 was installed but its launcher could not be found.';
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

function StopInstalledLauncher(): String;
var
  Python, Script: String;
  ResultCode: Integer;
begin
  Result := '';
  Python := ExpandConstant('{app}\launcher\.venv\Scripts\pythonw.exe');
  Script := ExpandConstant('{app}\launcher\windows_start.pyw');
  if FileExists(Python) and FileExists(Script) then
    if not RunHidden(Python, '"' + Script + '" --stop-existing', ResultCode) or (ResultCode <> 0) then
      Result := 'OpenAlma is still running. Use Exit in OpenAlma, then click Retry.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := StopInstalledLauncher();
  if Result = '' then
    Result := EnsurePrerequisites();
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
begin
  Result := StopInstalledLauncher() = '';
  if not Result then
    MsgBox('OpenAlma is still running. Use Exit in OpenAlma, then retry uninstall.', mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppsRoot, Marker, Owner: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveEverything := MsgBox(
      'Keep installed components, settings, and soul data?'#13#10#13#10 +
      'Choose Yes to keep them (recommended), or No to consider removing everything.',
      mbConfirmation, MB_YESNO
    ) = IDNO;
    if RemoveEverything then
      RemoveEverything := MsgBox(
        'Remove EVERYTHING in ' + ExpandConstant('{localappdata}\OpenAlma') + '?'#13#10 +
        'This permanently deletes installed components and soul data.',
        mbError, MB_YESNO
      ) = IDYES;
  end;
  if (CurUninstallStep = usPostUninstall) and RemoveEverything then
  begin
    AppsRoot := ExpandConstant('{localappdata}\OpenAlma');
    Marker := AppsRoot + '\.openalma-installer-root';
    if not LoadStringFromFile(Marker, Owner) or (CompareText(Trim(Owner), AppsRoot) <> 0) then
      MsgBox('OpenAlma refused to remove an Apps root it does not own: ' + AppsRoot, mbError, MB_OK)
    else begin
      DelTree(AppsRoot, True, True, True);
      DelTree(ExpandConstant('{userprofile}\.config\openalma-launcher'), True, True, True);
    end;
  end;
end;
