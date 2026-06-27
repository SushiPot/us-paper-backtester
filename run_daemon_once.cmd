@echo off
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PROJECT_PYTHON%" (
  echo Bundled Python not found: %PROJECT_PYTHON%
  pause
  exit /b 1
)

"%PROJECT_PYTHON%" daemon_main.py --once --mode online

pause
