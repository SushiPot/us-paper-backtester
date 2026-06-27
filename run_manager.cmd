@echo off
setlocal
cd /d "%~dp0"

echo [START] Running Overall Manager once in LOCAL mode with QQ Mail notification conditions
echo [INFO] Email is sent only when a trade, loss, or profit condition is detected.
echo [INFO] Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manager_with_email.ps1" -Mode local
