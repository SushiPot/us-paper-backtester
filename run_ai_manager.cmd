@echo off
setlocal
cd /d "%~dp0"

if "%OPENROUTER_API_KEY%"=="" (
  echo [WARN] OPENROUTER_API_KEY is not set. LLM Agent will be skipped.
  echo [INFO] Set it with: setx OPENROUTER_API_KEY "your_key"
)

if "%OPENROUTER_MODEL%"=="" (
  echo [INFO] OPENROUTER_MODEL is not set. Defaulting to the project OpenRouter model.
)

echo [START] Running AI Overall Manager once with OpenRouter free-first mode
echo [INFO] Email is sent only when a trade, loss, or profit condition is detected.
echo [INFO] Use your QQ Mail authorization code, not your QQ login password.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_manager_with_email.ps1" -Mode ai
