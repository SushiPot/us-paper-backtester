@echo off
setlocal
cd /d "%~dp0"
call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1
echo Running universe filter...
"%PROJECT_PYTHON%" universe_main.py
pause
