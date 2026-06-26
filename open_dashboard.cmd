@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

"%PROJECT_PYTHON%" dashboard.py
if errorlevel 1 (
  echo [ERROR] Dashboard generation failed.
  pause
  exit /b 1
)

start "" "%CD%\outputs\dashboard.html"
echo [OK] Dashboard opened.
