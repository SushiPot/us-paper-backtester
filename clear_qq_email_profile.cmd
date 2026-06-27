@echo off
setlocal
cd /d "%~dp0"

echo Removing saved QQ Mail encrypted profile...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\clear_email_profile.ps1"

echo.
pause
