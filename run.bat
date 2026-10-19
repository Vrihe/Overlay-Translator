@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:: Starts the app from .venv with normal user rights.
:: Global hotkeys work without admin rights. They are not delivered while an
:: app running as administrator (e.g. some games) has focus; only for that case
:: use --admin. Elevation runs this folder's code as administrator, so anything
:: able to edit the project files would get admin rights too.
:: Usage:
::   run.bat              - no console window (pythonw)
::   run.bat --console    - keep the console open to see logs and errors
::   run.bat --admin      - re-launch as administrator (UAC prompt)

set "CONSOLE=0"
set "ELEVATE=0"
for %%A in (%*) do (
    if /i "%%~A"=="--console" set "CONSOLE=1"
    if /i "%%~A"=="--admin" set "ELEVATE=1"
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found. Run install.bat first
    pause
    exit /b 1
)

if "%ELEVATE%"=="0" goto :launch
net session >nul 2>&1
if not errorlevel 1 goto :launch

:: Not elevated yet: re-run this script as administrator and exit.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
if errorlevel 1 (
    echo Admin rights were not granted. To run without them: run.bat
    pause
    exit /b 1
)
exit /b 0

:launch
if "%CONSOLE%"=="0" (
    start "" ".venv\Scripts\pythonw.exe" main.py
    exit /b 0
)
".venv\Scripts\python.exe" main.py
echo.
echo The app exited (code %errorlevel%).
pause
