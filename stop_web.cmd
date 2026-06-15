@echo off
setlocal

set "WEB_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "127.0.0.1:5000" ^| findstr "LISTENING"') do set "WEB_PID=%%P"

if not defined WEB_PID (
  echo [INFO] No local web server is listening on 127.0.0.1:5000.
  exit /b 0
)

echo [STOP] Stopping local web server PID %WEB_PID%
taskkill /PID %WEB_PID% /F
