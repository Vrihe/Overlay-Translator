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
echo   Translator Overlay ^| Установка зависимостей
echo ============================================================
echo.

if exist "%VENV_PY%" (
    echo [1/3] Виртуальное окружение .venv уже есть
    goto :deps
)

echo [1/3] Создаю виртуальное окружение .venv...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if not exist "%VENV_PY%" (
    echo.
    echo ОШИБКА: не удалось создать .venv. Установите Python 3.10+ с python.org
    echo и отметьте "Add python.exe to PATH".
    goto :fail
)

:deps
echo.
echo [2/3] Обновляю pip...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo.
echo [3/3] Устанавливаю зависимости из requirements.txt (первый раз - несколько минут)...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if /i "%~1"=="--gpu" (
    echo.
    echo [+] Устанавливаю cuBLAS для GPU ^(requirements-gpu.txt, ~740 MB^)...
    "%VENV_PY%" -m pip install -r requirements-gpu.txt
    if errorlevel 1 goto :fail
)

echo.
echo ============================================================
echo   ГОТОВО
echo   Модель для офлайн-перевода: download_model.bat
echo   Запуск приложения:          run.bat
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo УСТАНОВКА НЕ УДАЛАСЬ - смотрите вывод выше.
pause
exit /b 1
