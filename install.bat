@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:: Creates .venv (if missing) and installs the Python dependencies into it.
:: Usage:
::   install.bat         - base dependencies (requirements.txt)
::   install.bat --gpu   - plus cuBLAS for GPU inference of the local NLLB model

set "VENV_PY=.venv\Scripts\python.exe"

echo ============================================================
echo   Translator Overlay ^| Installing dependencies
echo ============================================================
echo.

if exist "%VENV_PY%" (
    echo [1/3] Virtual environment .venv already exists
    goto :deps
)

echo [1/3] Creating virtual environment .venv...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if not exist "%VENV_PY%" (
    echo.
    echo ERROR: failed to create .venv. Install Python 3.10+ from python.org
    echo and check "Add python.exe to PATH".
    goto :fail
)

:deps
echo.
echo [2/3] Upgrading pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo.
echo [3/3] Installing dependencies from requirements.txt (first run takes a few minutes)...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if /i "%~1"=="--gpu" (
    echo.
    echo [+] Installing cuBLAS for GPU ^(requirements-gpu.txt, ~740 MB^)...
    "%VENV_PY%" -m pip install -r requirements-gpu.txt
    if errorlevel 1 goto :fail
)

echo.
echo ============================================================
echo   DONE
echo   Offline translation model: download_model.bat
echo   Launch the app:             run.bat
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo INSTALLATION FAILED - see the output above.
pause
exit /b 1
