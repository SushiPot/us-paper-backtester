@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [START] Running safe self-update workflow...
"%PROJECT_PYTHON%" self_update_main.py %*
if errorlevel 1 goto failed

echo [OK] Self-update workflow completed.
pause
exit /b 0

:failed
echo [ERROR] Self-update workflow failed.
pause
exit /b 1
