@echo off
rem Start the Finzo hands-free voice service in the background.
rem No administrator rights needed. Stop it with stop_finzo_voice.bat.
setlocal
cd /d "%~dp0backend"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Could not find backend\.venv. Create it first:
    echo     cd backend
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from voice.handsfree.state import read_status; sys.exit(0 if read_status().get('running') else 1)" >nul 2>&1
if not errorlevel 1 (
    echo Finzo voice is already running.
    exit /b 0
)

rem pythonw has no console window, so the service keeps running after this
rem window closes. Everything it prints goes to backend\.finzo\voice.log.
start "" /B ".venv\Scripts\pythonw.exe" -m voice.main

echo Finzo voice is starting in the background. Loading speech models takes a
echo few seconds the first time. Then say "Hey Finzo".
echo Log:    %~dp0backend\.finzo\voice.log
echo Check:  cd backend ^&^& .venv\Scripts\python -m voice.main --selftest
endlocal
