@echo off
setlocal
cd /d "%~dp0"

echo [START] Setting up US Paper Backtester for standalone Windows use
echo [INFO] This creates .venv and installs project dependencies.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_standalone.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] Standalone setup failed.
  pause
  exit /b 1
)

echo.
echo [OK] Standalone setup completed.
echo [NEXT] You can run run_manager.cmd, run_daemon.cmd, run_web.cmd, or status_check.cmd without opening Codex.
pause
