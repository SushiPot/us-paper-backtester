@echo off
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PROJECT_PYTHON%" (
  echo Bundled Python not found: %PROJECT_PYTHON%
  pause
  exit /b 1
)

echo Starting US Paper Backtester daemon in ONLINE mode...
echo Press Ctrl+C to stop.
"%PROJECT_PYTHON%" daemon_main.py --mode online

pause
