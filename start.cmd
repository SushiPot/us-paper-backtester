@echo off
setlocal
cd /d "%~dp0"
call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1
"%PROJECT_PYTHON%" app_main.py %*
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%
