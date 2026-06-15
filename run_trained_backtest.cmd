@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [START] Running trained-parameter backtest
"%PROJECT_PYTHON%" trained_main.py
