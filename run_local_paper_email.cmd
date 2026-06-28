@echo off
setlocal
cd /d "%~dp0"

echo [START] Running Local Paper once with QQ Mail notification conditions
echo [INFO] Email is sent when a virtual trade, loss, or profit condition is detected.
echo [INFO] Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_local_paper_with_email.ps1"
pause
