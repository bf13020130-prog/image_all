@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title Design Output Web Platform

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python 3.12 or add it to PATH.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
    echo Edit .env later if you need to change the admin password or port.
    echo.
  )
)

python -m platform_backend.app.launcher
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Launcher exited with error code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
