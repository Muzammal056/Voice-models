@echo off
title Voice App
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo The Python environment is missing.
  pause
  exit /b 1
)

netstat -ano | findstr ":7860" | findstr "LISTENING" >nul
if %errorlevel%==0 (
  echo App is already running. Opening the browser...
  start "" http://127.0.0.1:7860
  exit /b 0
)

echo Starting the app...
echo Keep this window open. Close it to stop the server.
echo.
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:7860"
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
