@echo off
setlocal
cd /d "%~dp0"

echo [CHECK] Current repository:
git status --short --branch
if errorlevel 1 goto failed

echo.
echo [ACTION] Pushing main to GitHub...
git push origin main
if errorlevel 1 goto failed

echo [OK] GitHub push completed.
pause
exit /b 0

:failed
echo [ERROR] Git operation failed. Check network, GitHub login, and repository path.
pause
exit /b 1
