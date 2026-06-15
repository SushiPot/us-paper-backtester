@echo off
setlocal
cd /d "%~dp0"

echo [CHECK] Listening processes on port 5000
netstat -ano | findstr :5000
if errorlevel 1 echo [WARN] Nothing is listening on port 5000.

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [CHECK] Requesting http://127.0.0.1:5000
"%PROJECT_PYTHON%" -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:5000', timeout=5); body=r.read().decode('utf-8', errors='replace'); print('HTTP', r.status); print('US Paper Backtester' in body)"
