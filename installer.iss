; Video Downloader - Inno Setup kurulum betigi
; Onedir derlemesini tek dosyalik "Kurulum.exe" haline getirir.
; Derleme: ISCC.exe installer.iss

#define MyAppName "Video Downloader"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "hayatexe"
#define MyAppURL "https://github.com/hayatexe/video-downloader"
#define MyAppExeName "Video Downloader.exe"

[Setup]
AppId={{9C4E6A2F-3B7D-4E8A-9F1C-2B8D51E04A67}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; Kurulum exe'sinin kendi meta verisi. Imzasiz oldugu icin SmartScreen
; "yayinci bilinmiyor" diyecek, ama dosya adi yerine duzgun bir uygulama
; adi ve surum gostermesini sagliyor.
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Kurulum
VersionInfoProductName={#MyAppName}
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

[InstallDelete]
; Inno varsayilan olarak eski dosyalari SILMEZ, sadece uzerine yazar. Bu
; surumde paket yapisi degisti (ffmpeg tasindi, yt_dlp runtime/ altina gecti),
; dolayisiyla temizlenmezse eski surumden ~450 MB olu dosya kaliyordu -- ve
; _internal sys.path'te oldugu icin eski bir yt_dlp kopyasi orada durmamali.
; Ikisi de her kurulumda tamamen yeniden yaziliyor, iclerinde kullanici
; verisi yok (indirmeler {app}\downloads altinda, o korunuyor).
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\ffmpeg"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; Otomatik guncelleme sessiz kurulum yapiyor (updater.SILENT_FLAGS); bitince
; uygulamayi kurulum kendisi yeniden acsin.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\downloads"
