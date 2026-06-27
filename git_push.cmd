@echo off
setlocal
cd /d "%~dp0"

echo [CHECK] Current repository:
git status --short --branch
if errorlevel 1 goto failed

echo.
echo [ACTION] Pushing main to GitHub...
git push origin main
if errorlevel 1 goto api_fallback

echo [OK] GitHub push completed.
pause
exit /b 0

:api_fallback
echo.
echo [WARN] Standard git push failed. Trying GitHub API fallback...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\github_api_sync_main.ps1"
if errorlevel 1 goto failed

echo [OK] GitHub sync completed through API fallback.
pause
exit /b 0

:failed
echo [ERROR] Git operation failed. Check network, GitHub login, and repository path.
pause
exit /b 1
