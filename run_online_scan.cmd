@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [START] Running quick online project scan
echo [INFO] This skips local paper trading and heavy research reports.
echo [INFO] Optional: set GITHUB_TOKEN to raise GitHub API rate limits.
"%PROJECT_PYTHON%" agents_main.py --once --mode online --skip-local-paper --skip-research
pause
