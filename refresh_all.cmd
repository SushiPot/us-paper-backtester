@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

echo [STEP] Refreshing free online data...
"%PROJECT_PYTHON%" online_data_main.py
if errorlevel 1 goto failed

echo [STEP] Running local paper simulation once...
"%PROJECT_PYTHON%" local_paper_main.py --once
if errorlevel 1 goto failed

echo [STEP] Regenerating dashboard...
"%PROJECT_PYTHON%" dashboard.py
if errorlevel 1 goto failed

echo [STEP] Printing current status...
"%PROJECT_PYTHON%" status_main.py
if errorlevel 1 goto failed

echo [OK] Refresh workflow completed.
pause
exit /b 0

:failed
echo [ERROR] Refresh workflow failed.
pause
exit /b 1
