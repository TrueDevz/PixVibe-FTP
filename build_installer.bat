@echo off
title PixVibe FTP - Installer Builder
echo ========================================================
echo   Building PixVibe FTP Windows Installer
echo ========================================================
echo.

echo [1/3] Cleaning previous builds...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo [2/3] Compiling standalone executable with PyInstaller...
pyinstaller PixVibeFTP.spec --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller compilation failed!
    pause
    exit /b %errorlevel%
)

echo.
echo [3/3] Generating Windows Setup Installer with Inno Setup...
"C:\Users\PixVibe\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
if %errorlevel% neq 0 (
    echo [ERROR] Inno Setup compilation failed!
    pause
    exit /b %errorlevel%
)

echo.
echo ========================================================
echo   SUCCESS! Installer created:
echo   dist_installer\PixVibeFTP-Setup-v1.0.exe
echo ========================================================
echo.
pause
