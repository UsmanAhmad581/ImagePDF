; Inno Setup script - creates installer_output\ImagePDF-Setup.exe
[Setup]
AppName=Image to PDF
AppVersion=1.0.0
AppPublisher=ImagePDF
DefaultDirName={autopf}\ImagePDF
DefaultGroupName=Image to PDF
OutputDir=installer_output
OutputBaseFilename=ImagePDF-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ImagePDF.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\ImagePDF\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Image to PDF"; Filename: "{app}\ImagePDF.exe"
Name: "{autodesktop}\Image to PDF"; Filename: "{app}\ImagePDF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ImagePDF.exe"; Description: "Launch Image to PDF"; Flags: nowait postinstall skipifsilent
