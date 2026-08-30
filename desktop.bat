@echo off
rem Desktop app launcher: opens the control panel in a standalone desktop window.
rem Launches without a console window (pythonw). Errors go to logs\desktop_app.log.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
start "" ".venv\Scripts\pythonw.exe" desktop_app.py >> logs\desktop_app.log 2>&1
endlocal
