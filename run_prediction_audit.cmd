@echo off
setlocal
cd /d "%~dp0"
call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1
"%PROJECT_PYTHON%" prediction_audit_main.py
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
