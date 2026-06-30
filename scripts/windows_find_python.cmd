@echo off
set "PROJECT_PYTHON="
set "PROJECT_ROOT=%~dp0.."
set "PROJECT_VENV=%PROJECT_ROOT%\.venv"

if exist "%PROJECT_VENV%\Scripts\python.exe" (
  set "PROJECT_PYTHON=%PROJECT_VENV%\Scripts\python.exe"
  goto verify
)

call "%~dp0windows_find_base_python.cmd"
if errorlevel 1 exit /b 1

echo [INFO] Creating local virtual environment: %PROJECT_VENV%
"%BASE_PYTHON%" -m venv "%PROJECT_VENV%"
if errorlevel 1 (
  echo [ERROR] Failed to create local virtual environment.
  exit /b 1
)

set "PROJECT_PYTHON=%PROJECT_VENV%\Scripts\python.exe"

:verify
"%PROJECT_PYTHON%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Local Python is not working: %PROJECT_PYTHON%
  echo [FIX] Delete .venv and run setup_standalone.cmd again.
  exit /b 1
)

"%PROJECT_PYTHON%" -c "import flask, pandas, yfinance" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing project dependencies into .venv...
  "%PROJECT_PYTHON%" -m pip install --upgrade pip
  if errorlevel 1 exit /b 1
  "%PROJECT_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
  )
)

exit /b 0
