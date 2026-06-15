@echo off
setlocal
cd /d "%~dp0"

call scripts\windows_find_python.cmd
if errorlevel 1 exit /b 1

if "%OPENROUTER_API_KEY%"=="" (
  echo [WARN] OPENROUTER_API_KEY is not set. LLM Agent will be skipped.
  echo [INFO] Set it with: setx OPENROUTER_API_KEY "your_key"
)

if "%OPENROUTER_MODEL%"=="" (
  echo [INFO] OPENROUTER_MODEL is not set. Defaulting to openrouter/free.
)

echo [START] Running AI Overall Manager once with OpenRouter free-first mode
"%PROJECT_PYTHON%" agents_main.py --once --online --llm
