@echo off
setlocal
cd /d "%~dp0"

echo Starting US Paper Backtester daemon in ONLINE mode with QQ Mail notifications...
echo Press Ctrl+C to stop.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_daemon_with_email.ps1" -Mode online
pause
