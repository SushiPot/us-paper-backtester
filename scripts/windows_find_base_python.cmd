@echo off
set "BASE_PYTHON="

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "BASE_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined BASE_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "BASE_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not defined BASE_PYTHON (
  for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "BASE_PYTHON=%%P"
)
if not defined BASE_PYTHON (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "BASE_PYTHON=%%P"
)
if not defined BASE_PYTHON (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "BASE_PYTHON=%%P"
)

if defined BASE_PYTHON (
  echo %BASE_PYTHON% | findstr /i "\\Microsoft\\WindowsApps\\python.exe" >nul
  if not errorlevel 1 set "BASE_PYTHON="
)

if defined BASE_PYTHON (
  echo %BASE_PYTHON% | findstr /i "\\.cache\\codex-runtimes\\" >nul
  if not errorlevel 1 (
    if /i not "%ALLOW_CODEX_RUNTIME%"=="1" set "BASE_PYTHON="
  )
)

if not defined BASE_PYTHON (
  echo [ERROR] No standalone Python installation was found.
  echo [FIX] Run setup_standalone.cmd to install Python and create .venv.
  echo [FIX] Or install Python 3.12 from https://www.python.org/downloads/windows/
  echo [FIX] Then run setup_standalone.cmd again.
  exit /b 1
)

"%BASE_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.11 or newer is required: %BASE_PYTHON%
  exit /b 1
)

exit /b 0
