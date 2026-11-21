@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: transcribe.bat "C:\path\to\video.mp4"
  exit /b 1
)
".venv\Scripts\python.exe" transcribe.py %*
