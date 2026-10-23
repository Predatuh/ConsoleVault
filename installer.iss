; ConsoleVault installer (built automatically by GitHub Actions)
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E2A-9C1F-3D5E7A9B1C24}
AppName=ConsoleVault
AppVersion={#MyAppVersion}
AppVerName=ConsoleVault {#MyAppVersion}
AppPublisher=Tanner
; per-user install: no admin prompt, so updates install silently
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\ConsoleVault
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=ConsoleVault-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ConsoleVault.exe
UninstallDisplayName=ConsoleVault

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; wipe old program files on update (your emulators/games live elsewhere and are never touched)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\ConsoleVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ConsoleVault"; Filename: "{app}\ConsoleVault.exe"
Name: "{autodesktop}\ConsoleVault"; Filename: "{app}\ConsoleVault.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ConsoleVault.exe"; Description: "Launch ConsoleVault"; Flags: nowait postinstall skipifsilent
