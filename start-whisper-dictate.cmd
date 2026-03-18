@echo off
set VENV=D:\DEV\PROJEKTE\whisper-dictate\.venv\Scripts
set SCRIPT=D:\DEV\PROJEKTE\whisper-dictate\dictate.py

tasklist /fi "IMAGENAME eq WhisperDictate.exe" 2>nul | find "WhisperDictate" >nul
if not errorlevel 1 (
    echo WhisperDictate laeuft bereits.
    exit /b
)

if not exist "%VENV%\WhisperDictate.exe" copy "%VENV%\pythonw.exe" "%VENV%\WhisperDictate.exe" >nul

start "" /b "%VENV%\WhisperDictate.exe" "%SCRIPT%"
