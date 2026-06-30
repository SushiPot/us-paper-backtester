@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo Running market cache warmup...
"%PROJECT_PYTHON%" cache_warmup_main.py --limit 5
pause
