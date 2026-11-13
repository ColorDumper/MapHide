; MapHide installer (Inno Setup 6).
;
; Wraps the PyInstaller folder build in dist\MapHide. Build it with:
;   ISCC installer\MapHide.iss /DAppVersion=1.2.3 /DOutputName=MapHide-v1.2.3-setup
;
; Installs for the current user only, so it needs no administrator prompt.
; Settings live in %APPDATA%\MapHide, outside the install folder, so
; installing a newer version over an older one keeps them.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef OutputName
  #define OutputName "MapHide-setup"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\MapHide"
#endif

; Must match MUTEX_NAME in maphide/single_instance.py.
#define AppMutexName "Local\MapHide-SingleInstance"
; Must match APP_USER_MODEL_ID in maphide/paths.py, so the Start menu
; shortcut and the running window share one taskbar button.
#define AppUserModelID "MapHide.App"

[Setup]
; Never change AppId: Windows uses it to recognise an update to the same app.
AppId={{6B8B294C-F01D-41AA-AD4C-CA7085442921}
AppName=MapHide
AppVersion={#AppVersion}
AppVerName=MapHide {#AppVersion}
AppPublisher=ColorDumper
AppPublisherURL=https://github.com/ColorDumper/MapHide
AppSupportURL=https://github.com/ColorDumper/MapHide/issues
AppUpdatesURL=https://github.com/ColorDumper/MapHide/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=MapHide
VersionInfoDescription=MapHide Setup
PrivilegesRequired=lowest
DefaultDirName={autopf}\MapHide
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=..\MapHide.ico
UninstallDisplayIcon={app}\MapHide.exe
UninstallDisplayName=MapHide
OutputDir=..\dist
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
; MapHide is closed with --quit below, which hides the overlay in OBS first.
CloseApplications=no
RestartApplications=no
; The old version's files are deleted before the new ones are copied (see
; [InstallDelete]), so a cancel in between would leave MapHide unable to start.
AllowCancelDuringInstall=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clear out the previous version's files first, so an update leaves nothing
; old behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MapHide"; Filename: "{app}\MapHide.exe"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\MapHide"; Filename: "{app}\MapHide.exe"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\MapHide.exe"; Description: "{cm:LaunchProgram,MapHide}"; Flags: nowait postinstall skipifsilent
; MapHide's own updater runs this setup with /RELAUNCH=1 to open it again after.
Filename: "{app}\MapHide.exe"; Flags: nowait; Check: RelaunchRequested

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{%TEMP}\MapHide-update"

[Code]
var
  RemoveSettings: Boolean;

function RelaunchRequested(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

// Close a running MapHide the same way Exit in the tray does, so the overlay
// is hidden in OBS before its files are replaced or removed.
procedure QuitMapHide(const ExePath: String);
var
  ResultCode: Integer;
begin
  if FileExists(ExePath) then
    Exec(ExePath, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  QuitMapHide(ExpandConstant('{app}\MapHide.exe'));
  if CheckForMutexes('{#AppMutexName}') then
    Result := 'MapHide is still running. Close it (right-click its tray icon, then Exit), then click Back and Next to try again.';
end;

function InitializeUninstall(): Boolean;
var
  Labels: TArrayOfString;
begin
  Result := True;
  QuitMapHide(ExpandConstant('{app}\MapHide.exe'));
  if CheckForMutexes('{#AppMutexName}') then
  begin
    MsgBox('MapHide is still running. Close it (right-click its tray icon, then Exit), then try again.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // A silent uninstall always keeps settings.
  RemoveSettings := False;
  if not UninstallSilent() then
  begin
    SetArrayLength(Labels, 2);
    Labels[0] := 'Remove MapHide only'#13#10'Keep your settings in case you install MapHide again.';
    Labels[1] := 'Remove MapHide and my settings'#13#10'Also delete your OBS details, key and other settings.';
    case TaskDialogMsgBox('How do you want to remove MapHide?', '', mbConfirmation, MB_YESNO, Labels, 0) of
      IDYES: RemoveSettings := False;
      IDNO: RemoveSettings := True;
    else
      Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveSettings then
    DelTree(ExpandConstant('{userappdata}\MapHide'), True, True, True);
end;
