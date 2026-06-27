@echo off
setlocal
cd /d "%~dp0"
echo Running universe filter...
python universe_main.py
pause
