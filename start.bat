@echo off
rem Double-click to start the Reading Journal. The first run sets things up.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time...
    py -3 -m venv .venv
    if errorlevel 1 goto nopython
)

".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installing the journal's packages failed. Check your internet connection and try again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run.py
pause
exit /b

:nopython
echo.
echo Python wasn't found. Install Python 3.13 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer. Then double-click start.bat again.
pause
exit /b 1
