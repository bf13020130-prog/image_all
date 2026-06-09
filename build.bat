@echo off
setlocal
cd /d "%~dp0"
call npm install
if errorlevel 1 exit /b 1

call npm run dist:platform-desktop
if errorlevel 1 exit /b 1
