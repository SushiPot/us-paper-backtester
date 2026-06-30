@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo Starting US Paper Backtester daemon in ONLINE mode...
echo Press Ctrl+C to stop.
"%PROJECT_PYTHON%" daemon_main.py --mode online

pause
