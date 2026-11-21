@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" setup_kokoro.py
if errorlevel 1 echo Kokoro setup failed. Read the message above.
pause
