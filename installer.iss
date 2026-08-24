; Video Downloader - Inno Setup kurulum betigi
; Onedir derlemesini tek dosyalik "Kurulum.exe" haline getirir.
; Derleme: ISCC.exe installer.iss

#define MyAppName "Video Downloader"
#define MyAppVersion "1.2.0"
#define MyAppExeName "Video Downloader.exe"

[Setup]
AppId={{9C4E6A2F-3B7D-4E8A-9F1C-2B8D51E04A67}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
; Yonetici izni GEREKMEZ - kullanicinin kendi klasorune kurulur
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Video Downloader Kurulum
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; ffmpeg PyInstaller ile paketlenmiyor (DLL'leri _internal koküne de kopyalayip
; 161 MB'i iki kere yaziyordu). build_exe.bat onu dist\{#MyAppName}\ffmpeg
; altina kopyalar, asagidaki wildcard da beraberinde tasir.
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\downloads"
