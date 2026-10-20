; Inno Setup script for the Windows installer. Built by packaging/build.sh on Windows:
;   ISCC /DMyVersion=0.2.0 packaging\windows\discoal-studio.iss
#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
AppId={{8F6B1C2E-4D3A-4E5B-9C7D-2A1B3C4D5E6F}
AppName=discoal Studio
AppVersion={#MyVersion}
AppVerName=discoal Studio {#MyVersion}
AppPublisher=Tanvir Anjum Joarder
AppPublisherURL=https://github.com/tanviranjumjoarder/discoal-studio
DefaultDirName={autopf}\discoal Studio
DefaultGroupName=discoal Studio
DisableProgramGroupPage=yes
; Installs for the current user without admin rights (can be switched to all users in the wizard).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=discoal-studio-{#MyVersion}-windows-x64-setup
UninstallDisplayIcon={app}\discoal-studio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\discoal-studio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\discoal Studio"; Filename: "{app}\discoal-studio.exe"
Name: "{group}\Uninstall discoal Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\discoal Studio"; Filename: "{app}\discoal-studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\discoal-studio.exe"; Description: "Start discoal Studio"; Flags: nowait postinstall skipifsilent
