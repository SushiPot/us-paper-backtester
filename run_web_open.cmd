@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

"%PROJECT_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000', timeout=2).read()" >nul 2>nul
if not errorlevel 1 (
  echo [OK] Website is already running. Opening browser...
  start "" "http://127.0.0.1:5000"
  exit /b 0
)

echo [START] Starting local web app at http://127.0.0.1:5000
echo [INFO] Browser will open automatically when the website is ready.
echo [INFO] Keep this window open. Press Ctrl+C to stop the web server.

start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\open_web_when_ready.ps1" -Url "http://127.0.0.1:5000" -TimeoutSeconds 45
"%PROJECT_PYTHON%" web_app.py
