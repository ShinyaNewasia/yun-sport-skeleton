@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" accounts.py whoami
echo.
".venv\Scripts\python.exe" main.py %*
pause
