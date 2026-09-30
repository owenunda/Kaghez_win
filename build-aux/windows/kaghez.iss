; Inno Setup script for the Windows installer. Build the app with
; build.sh first, then run: ISCC.exe build-aux\windows\kaghez.iss
; Paths are relative to this file. Set KAGHEZ_VERSION to stamp a version.

#define AppVersion GetEnv("KAGHEZ_VERSION")
#if AppVersion == ""
  #define AppVersion "0.8.8"
#endif
#define BuildDir "..\..\_build-windows"

[Setup]
AppId={{6B0E3C8B-5E2B-4F4B-9C7E-2A1D9E4B7C31}
AppName=Kaghez
AppVersion={#AppVersion}
AppPublisher=Kaghez
AppPublisherURL=https://github.com/owenunda/Kaghez_win
DefaultDirName={autopf}\Kaghez
DefaultGroupName=Kaghez
DisableProgramGroupPage=yes
LicenseFile=..\..\COPYING
OutputDir={#BuildDir}\installer
OutputBaseFilename=Kaghez-{#AppVersion}-setup-x64
SetupIconFile={#BuildDir}\kaghez.ico
UninstallDisplayIcon={app}\Kaghez.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install by default (no admin prompt); users can choose all-users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; Kaghez.exe keeps the bundled java.exe alive; make sure both are closed
; before files are replaced.
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Drop the previous version's bundle so old jars/DLLs don't pile up.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BuildDir}\dist\Kaghez\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kaghez"; Filename: "{app}\Kaghez.exe"
Name: "{autodesktop}\Kaghez"; Filename: "{app}\Kaghez.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kaghez.exe"; Description: "{cm:LaunchProgram,Kaghez}"; Flags: nowait postinstall skipifsilent
