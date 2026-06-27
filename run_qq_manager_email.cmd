@echo off
setlocal
cd /d "%~dp0"

echo Starting Manager with QQ Mail notification...
echo Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manager_with_email.ps1" -Mode local -SmtpHost "smtp.qq.com" -SmtpPort "587"

echo.
pause
