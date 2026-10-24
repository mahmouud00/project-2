; MYTech Solutions Server installer (Inno Setup 6). Built by .github/workflows/windows-release.yml:
;   iscc /DMyVersion=0.1.0 /DStage=build\stage /DOutDir=build\out deploy\windows\MYTechServer.iss
; Stage layout: app\<version>\ (compiled server), pgsql\ (PostgreSQL binaries), service\ (WinSW + launcher),
;               scripts\ (setup/uninstall), redist\vc_redist.x64.exe, icon.ico

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif
#ifndef Stage
  #define Stage "..\..\build\stage"
#endif
#ifndef OutDir
  #define OutDir "..\..\build\out"
#endif

[Setup]
AppId={{6F1D3C1E-8A55-4B8B-9C1E-5D7F3A2B9E10}
AppName=MYTech Solutions Server
AppVersion={#MyVersion}
AppVerName=MYTech Solutions Server {#MyVersion}
AppPublisher=MYTech Solutions
DefaultDirName=C:\MYTech
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=MYTech-Server-Setup-{#MyVersion}
SetupIconFile={#Stage}\icon.ico
UninstallDisplayIcon={app}\service\mytech-service.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#Stage}\app\{#MyVersion}\*"; DestDir: "{app}\app\{#MyVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\pgsql\*"; DestDir: "{app}\pgsql"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\service\*"; DestDir: "{app}\service"; Flags: ignoreversion recursesubdirs
Source: "{#Stage}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#Stage}\redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{app}\logs"
Name: "{app}\backups"; Flags: uninsneveruninstall
Name: "{app}\media"; Flags: uninsneveruninstall
Name: "{app}\license"; Flags: uninsneveruninstall
Name: "{app}\config"; Flags: uninsneveruninstall
Name: "{app}\pgdata"; Flags: uninsneveruninstall

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ runtime..."; Flags: waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall-server.ps1"" -Root ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveServices"

[Code]
var
  CompanyPage: TInputQueryWizardPage;
  Fresh: Boolean;

function IsFreshInstall(): Boolean;
begin
  Result := not FileExists(WizardDirValue() + '\config\.env');
end;

procedure InitializeWizard();
begin
  CompanyPage := CreateInputQueryPage(wpSelectDir, 'Company', 'The factory that will use this server',
    'Enter the company code (Latin letters/digits, e.g. NOUR), its name, and the password of the first user "admin".');
  CompanyPage.Add('Company code:', False);
  CompanyPage.Add('Company name:', False);
  CompanyPage.Add('Password for user "admin" (at least 8 characters):', True);
  CompanyPage.Add('Repeat the password:', True);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = CompanyPage.ID) and not IsFreshInstall();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: String;
  I: Integer;
begin
  Result := True;
  if CurPageID = CompanyPage.ID then
  begin
    Code := Trim(CompanyPage.Values[0]);
    if (Length(Code) < 2) or (Length(Code) > 20) then
    begin
      MsgBox('The company code must be 2 to 20 characters.', mbError, MB_OK); Result := False; Exit;
    end;
    for I := 1 to Length(Code) do
      if not (((Code[I] >= 'A') and (Code[I] <= 'Z')) or ((Code[I] >= 'a') and (Code[I] <= 'z')) or
              ((Code[I] >= '0') and (Code[I] <= '9')) or (Code[I] = '-') or (Code[I] = '_')) then
      begin
        MsgBox('The company code may contain only Latin letters, digits, - and _.', mbError, MB_OK); Result := False; Exit;
      end;
    if Trim(CompanyPage.Values[1]) = '' then
    begin
      MsgBox('Enter the company name.', mbError, MB_OK); Result := False; Exit;
    end;
    if Length(CompanyPage.Values[2]) < 8 then
    begin
      MsgBox('The password must be at least 8 characters.', mbError, MB_OK); Result := False; Exit;
    end;
    if CompanyPage.Values[2] <> CompanyPage.Values[3] then
    begin
      MsgBox('The two passwords are different.', mbError, MB_OK); Result := False; Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PwFile, Params, CoName: String;
  Fingerprint: AnsiString;
  Lines: TArrayOfString;
begin
  if CurStep = ssInstall then
    Fresh := IsFreshInstall();
  if CurStep = ssPostInstall then
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\setup-server.ps1') + '"' +
              ' -Root "' + ExpandConstant('{app}') + '" -Version "{#MyVersion}"';
    if Fresh then
    begin
      PwFile := ExpandConstant('{tmp}\admin-password.txt');
      SetArrayLength(Lines, 1);
      Lines[0] := CompanyPage.Values[2];
      SaveStringsToUTF8File(PwFile, Lines, False);   // Unicode-safe; read back by setup-server.ps1, then deleted
      CoName := Trim(CompanyPage.Values[1]);
      StringChangeEx(CoName, '"', '', True);
      Params := Params + ' -CompanyCode "' + Trim(CompanyPage.Values[0]) + '" -CompanyName "' + CoName + '"' +
                ' -AdminPasswordFile "' + PwFile + '"';
    end;
    WizardForm.StatusLabel.Caption := 'Setting up the database and the MYTech service (this can take a minute)...';
    if not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      MsgBox('The server setup did not finish. Details: ' + ExpandConstant('{app}\logs\install.log') + #13#10 +
             'Nothing was deleted; fix the problem and run the installer again.', mbError, MB_OK)
    else if LoadStringFromFile(ExpandConstant('{app}\license\fingerprint.txt'), Fingerprint) then
      MsgBox('MYTech server is running.' + #13#10#13#10 + 'Machine fingerprint (send it to MYTech for the licence):' + #13#10 +
             Fingerprint + #13#10#13#10 + '(saved in ' + ExpandConstant('{app}\license\fingerprint.txt') + ')', mbInformation, MB_OK);
    if Fresh then DeleteFile(ExpandConstant('{tmp}\admin-password.txt'));
  end;
end;
