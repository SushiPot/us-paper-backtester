@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

"%PROJECT_PYTHON%" status_main.py
pause
