@echo off
rem Stop the Finzo hands-free voice service started by start_finzo_voice.bat.
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
    echo Could not find backend\.venv.
    exit /b 1
)
".venv\Scripts\python.exe" -m voice.main --stop --log-file "%TEMP%\finzo_voice_stop.log"
endlocal
