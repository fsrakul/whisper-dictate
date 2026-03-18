@echo off
cd /d "%~dp0"
set VENV=%~dp0.venv\Scripts
set SCRIPT=%~dp0dictate.py

tasklist /fi "IMAGENAME eq WhisperDictate.exe" 2>nul | find "WhisperDictate" >nul
if not errorlevel 1 (
    echo WhisperDictate laeuft bereits, wird neu gestartet...
    taskkill /f /im WhisperDictate.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
)

if not exist "%VENV%\WhisperDictate.exe" copy "%VENV%\pythonw.exe" "%VENV%\WhisperDictate.exe" >nul

start "" /b "%VENV%\WhisperDictate.exe" "%SCRIPT%"
