@echo off
setlocal
cd /d "%~dp0"

echo Starting QQ Mail email test...
echo Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_email_test.ps1" -SmtpHost "smtp.qq.com" -SmtpPort "587"

echo.
pause
