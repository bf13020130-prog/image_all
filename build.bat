@echo off
setlocal
cd /d "%~dp0"
python prepare_runtime.py
if errorlevel 1 exit /b 1

call npm install
if errorlevel 1 exit /b 1

call npm run dist
if errorlevel 1 exit /b 1
