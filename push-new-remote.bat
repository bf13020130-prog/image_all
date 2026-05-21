@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-new-remote.ps1 -RemoteUrl "https://github.com/bf13020130-prog/image_all.git" -Branch main
if errorlevel 1 (
  echo Push failed.
  pause
  exit /b 1
)
echo Push complete.
pause
