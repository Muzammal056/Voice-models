@echo off
cd /d "%~dp0"
echo Installing the voice enhancers in a separate local runtime.
echo This downloads CPU inference libraries. Keep this window open.
".venv\Scripts\python.exe" setup_enhancers.py
if errorlevel 1 (echo Setup failed. Read the error above.) else (echo Setup complete. Restart Start App.bat.)
pause
