@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo    Video Downloader - Derleme + Kurulum Paketi
echo  ==========================================
echo.

:: Check for Python
where py >nul 2>&1
if errorlevel 1 (
    echo HATA: Python bulunamadi!
    echo https://www.python.org/downloads/ adresinden indirin.
    pause & exit /b 1
)

echo [1/3] Gerekli araclar yukleniyor...
py -3 -m pip install --quiet --upgrade pyinstaller "pywebview>=5.3" pystray pillow flask flask-cors "yt-dlp[default,curl-cffi]"
if errorlevel 1 ( echo Yuklenemedi! & pause & exit /b 1 )

echo [2/3] Uygulama derleniyor... (onedir modu: hizli acilis)
echo.

py -3 -m PyInstaller "Video Downloader.spec" --clean --noconfirm
if errorlevel 1 (
    echo.
    echo HATA: Derleme basarisiz!
    pause & exit /b 1
)

:: ffmpeg'i PyInstaller paketlemiyor (DLL'leri iki kere kopyaliyordu),
:: derlemeden sonra elle yanina koyuyoruz.
echo      ffmpeg kopyalaniyor...
if not exist "dist\Video Downloader\ffmpeg" mkdir "dist\Video Downloader\ffmpeg"
xcopy /Y /Q /E "ffmpeg\*" "dist\Video Downloader\ffmpeg\" >nul
if errorlevel 1 ( echo HATA: ffmpeg kopyalanamadi! & pause & exit /b 1 )

:: quickjs: girisli YouTube indirmeleri icin JS calistiricisi (2 MB).
:: Surum ve hash .github/workflows/release.yml ile ayni tutulmali.
echo      quickjs hazirlaniyor...
if not exist "jsruntime\qjs.exe" (
    if not exist jsruntime mkdir jsruntime
    powershell -NoProfile -Command "Invoke-WebRequest 'https://github.com/quickjs-ng/quickjs/releases/download/v0.17.0/qjs-windows-x86_64.exe' -OutFile 'jsruntime\qjs.exe'"
)
powershell -NoProfile -Command "if ((Get-FileHash 'jsruntime\qjs.exe' -Algorithm SHA256).Hash.ToLower() -ne '2aeabf0092c3262d6b2609824418f7dd7ed1f1df939f73b2b15645230cac0d77') { exit 1 }"
if errorlevel 1 ( echo HATA: qjs.exe hash uyusmuyor, jsruntime klasorunu silip tekrar deneyin! & pause & exit /b 1 )
if not exist "dist\Video Downloader\jsruntime" mkdir "dist\Video Downloader\jsruntime"
copy /Y "jsruntime\qjs.exe" "dist\Video Downloader\jsruntime\" >nul

:: --- Isteğe bagli kod imzalama ---------------------------------------------
:: Kod imzasi SmartScreen uyarisini zamanla ortadan kaldiran TEK yol; itibar
:: sertifikaya islendigi icin her yeni surumde sifirlanmaz. Sertifika yoksa
:: bu adim sessizce atlanir, derleme normal sekilde imzasiz devam eder.
::
:: Kullanmak icin sertifikanin parmak izini ortam degiskenine koy:
::   setx VD_SIGN_THUMBPRINT "a1b2c3..."
:: Sertifika Windows sertifika deposunda kurulu olmali (token/HSM dahil).
if defined VD_SIGN_THUMBPRINT (
    echo      Uygulama imzalaniyor...
    where signtool >nul 2>&1
    if errorlevel 1 (
        echo UYARI: signtool bulunamadi, imzalama atlandi.
        echo        Windows SDK gerekli: winget install Microsoft.WindowsSDK
    ) else (
        signtool sign /sha1 %VD_SIGN_THUMBPRINT% /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "dist\Video Downloader\Video Downloader.exe"
        if errorlevel 1 ( echo HATA: Uygulama imzalanamadi! & pause & exit /b 1 )
    )
) else (
    echo      Imzalama atlandi ^(VD_SIGN_THUMBPRINT tanimli degil^) - SmartScreen uyarisi cikacak.
)

echo [3/3] Kurulum paketi olusturuluyor...
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo UYARI: Inno Setup bulunamadi, kurulum paketi atlandi.
    echo Kurmak icin: winget install JRSoftware.InnoSetup
    echo Uygulama yine de hazir: dist\Video Downloader\Video Downloader.exe
    pause & exit /b 0
)

"%ISCC%" /Q installer.iss
if errorlevel 1 (
    echo HATA: Kurulum paketi olusturulamadi!
    pause & exit /b 1
)

:: Kurulum dosyasini da imzala (varsa)
if defined VD_SIGN_THUMBPRINT (
    where signtool >nul 2>&1
    if not errorlevel 1 (
        echo      Kurulum paketi imzalaniyor...
        signtool sign /sha1 %VD_SIGN_THUMBPRINT% /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "dist\Video Downloader Kurulum.exe"
        if errorlevel 1 ( echo HATA: Kurulum paketi imzalanamadi! & pause & exit /b 1 )
    )
)

:: SHA256 saglama toplami. Uygulamanin otomatik guncellemesi indirdigi dosyayi
:: bununla dogruluyor ve uyusmazsa kurulumu yapmiyor. Yayina (GitHub Release)
:: kurulum exe'si ile BIRLIKTE yuklenmesi SART, yoksa guncelleme durur.
echo      SHA256 hesaplaniyor...
powershell -NoProfile -Command "$h=(Get-FileHash 'dist\Video Downloader Kurulum.exe' -Algorithm SHA256).Hash.ToLower(); \"$h *Video Downloader Kurulum.exe\" | Set-Content -Encoding ascii 'dist\SHA256SUMS.txt'; Write-Host $h"
if errorlevel 1 ( echo HATA: SHA256 hesaplanamadi! & pause & exit /b 1 )

echo.
echo  ==========================================
echo   TAMAMLANDI!
echo  ==========================================
echo.
echo   Arkadaslarina atacagin dosya:
echo   dist\Video Downloader Kurulum.exe
echo.
echo   GitHub yayinina IKISINI de yukle:
echo     dist\Video Downloader Kurulum.exe
echo     dist\SHA256SUMS.txt
echo.
echo   (Yayini GitHub Actions da yapabilir: Actions -^> Release -^> Run workflow)
echo.
echo   Kurulum simdi baslatiliyor...
start "" "dist\Video Downloader Kurulum.exe"
explorer dist
pause
