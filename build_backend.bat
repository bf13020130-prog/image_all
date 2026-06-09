@echo off
setlocal
cd /d "%~dp0"
echo The legacy backend-exe build is retired for the current platform desktop app.
echo Use this maintained platform build instead:
echo.
echo   npm run dist:platform-desktop
echo.
exit /b 1
