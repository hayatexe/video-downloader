@echo off
cd /d "%~dp0"

:: Find Python (try py launcher first, then python, then full path)
set PYTHON=
where py >nul 2>&1 && set PYTHON=py -3
if "%PYTHON%"=="" (
    where python >nul 2>&1 && set PYTHON=python
)
if "%PYTHON%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
        set PYTHON="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    )
)
if "%PYTHON%"=="" (
    echo HATA: Python bulunamadi!
    echo Python'u su adresten indirin: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install dependencies silently if pywebview not present
%PYTHON% -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo Gerekli kutuphaneler yukleniyor, bir dakika bekleyin...
    %PYTHON% -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo HATA: Kutuphaneler yuklenemedi! Internete bagli oldugunuzdan emin olun.
        pause
        exit /b 1
    )
)

:: Launch the desktop app (no console window)
if "%PYTHON%"=="py -3" (
    start "" pyw -3 launcher.pyw
) else (
    start "" "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" launcher.pyw
)
