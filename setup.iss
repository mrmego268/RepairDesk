[Setup]
AppName=RepairDesk
AppVersion=1.0.0
DefaultDirName={autopf}\RepairDesk
DefaultGroupName=RepairDesk
OutputDir=dist_installer
OutputBaseFilename=RepairDeskSetup_1.0.0
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RepairDesk"; Filename: "{app}\main.exe"
[Tasks]
Name: "desktopicon"; Description: "إنشاء أيقونة على سطح المكتب"; GroupDescription: "خيارات إضافية:"; Flags: unchecked

[Run]
Filename: "{app}\main.exe"; Description: "تشغيل RepairDesk"; Flags: nowait postinstall skipifsilent
