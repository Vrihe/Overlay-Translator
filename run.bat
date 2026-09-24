@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:: Starts the app from .venv. Global hotkeys (keyboard) need admin rights,
:: so the script re-launches itself elevated (UAC prompt).
:: Usage:
::   run.bat              - no console window (pythonw)
::   run.bat --console    - keep the console open to see logs and errors
::   run.bat --no-admin   - do not request admin rights

set "CONSOLE=0"
set "ELEVATE=1"
for %%A in (%*) do (
    if /i "%%~A"=="--console" set "CONSOLE=1"
    if /i "%%~A"=="--no-admin" set "ELEVATE=0"
)

if not exist ".venv\Scripts\python.exe" (
    echo ОШИБКА: .venv не найден. Сначала запустите install.bat
    pause
    exit /b 1
)

if "%ELEVATE%"=="0" goto :launch
net session >nul 2>&1
if not errorlevel 1 goto :launch

:: Not elevated yet: re-run this script as administrator and exit.
if "%~1"=="" goto :elevate_noargs
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
goto :elevated
:elevate_noargs
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
:elevated
if errorlevel 1 (
    echo Права администратора не получены. Запуск без них: run.bat --no-admin
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
echo Приложение завершилось (код %errorlevel%).
pause
