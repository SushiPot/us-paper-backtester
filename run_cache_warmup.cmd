@echo off
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PROJECT_PYTHON%" (
  echo Bundled Python not found: %PROJECT_PYTHON%
  pause
  exit /b 1
)

echo Running market cache warmup...
"%PROJECT_PYTHON%" cache_warmup_main.py --limit 10
pause
