@echo off
rem Double-click while working on the app. Restarts by itself when the code changes.
rem Opens the sample journal in journal-demo, never your real one. Use start.bat for that.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run start.bat once first to set things up.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installing the journal's packages failed. Check your internet connection and try again.
    pause
    exit /b 1
)

if not exist "journal-demo\journal.db" (
    echo Making the sample journal...
    ".venv\Scripts\python.exe" seed.py
)

".venv\Scripts\python.exe" run.py --dev
pause
