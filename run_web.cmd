@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [START] Starting local web app at http://127.0.0.1:5000
echo [INFO] Python: %PROJECT_PYTHON%
echo [INFO] Press Ctrl+C to stop the web server.
"%PROJECT_PYTHON%" web_app.py
