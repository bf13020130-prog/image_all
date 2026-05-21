@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File scripts\package-platform-zip.ps1
if errorlevel 1 (
  echo Packaging failed.
  pause
  exit /b 1
)
echo Packaging complete.
pause
