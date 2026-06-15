@echo off
set "PROJECT_PYTHON="

if exist "%~dp0..\.venv\Scripts\python.exe" set "PROJECT_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not defined PROJECT_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PROJECT_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PROJECT_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PROJECT_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PROJECT_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PROJECT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined PROJECT_PYTHON set "PROJECT_PYTHON=python"

"%PROJECT_PYTHON%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No working Python interpreter was found.
  echo [FIX] Install Python 3.12 from https://www.python.org/downloads/windows/
  echo [FIX] Or disable Windows App Execution Alias for python.exe in Windows Settings.
  exit /b 1
)

"%PROJECT_PYTHON%" -c "import flask" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing project dependencies...
  "%PROJECT_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
  )
)

exit /b 0
