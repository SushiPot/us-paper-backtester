@echo off
setlocal
cd /d "%~dp0"

echo [START] Running Online Overall Manager once
echo [INFO] Optional: set GITHUB_TOKEN to raise GitHub API rate limits.
echo [INFO] Email is sent only when a trade, loss, or profit condition is detected.
echo [INFO] Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manager_with_email.ps1" -Mode online
