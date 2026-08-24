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
py -3 -m pip install --quiet --upgrade pyinstaller "pywebview>=5.3" pystray pillow flask flask-cors yt-dlp
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

echo.
echo  ==========================================
echo   TAMAMLANDI!
echo  ==========================================
echo.
echo   Arkadaslarina atacagin dosya:
echo   dist\Video Downloader Kurulum.exe
echo.
explorer dist
pause
