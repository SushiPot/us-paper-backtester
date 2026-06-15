@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [START] Running Overall Manager once
"%PROJECT_PYTHON%" agents_main.py --once
