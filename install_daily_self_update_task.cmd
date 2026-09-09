@echo off
setlocal
cd /d "%~dp0"

echo [START] Installing daily self-update scheduled task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_daily_self_update_task.ps1" %*
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to install daily self-update scheduled task.
  pause
  exit /b 1
)

echo.
echo [OK] Daily self-update scheduled task installed.
pause
