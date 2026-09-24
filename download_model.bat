@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:: Downloads the local NLLB model (~621 MB) into models\nllb-200-ct2-int8.
:: All arguments are forwarded to scripts\download_model.py, e.g.:
::   download_model.bat --revision v0-base
::   download_model.bat --dest D:\models\nllb-200-ct2-int8

set "VENV_PY=.venv\Scripts\python.exe"

echo ============================================================
echo   Translator Overlay ^| Загрузка модели NLLB (~621 MB)
echo ============================================================
echo.

if not exist "%VENV_PY%" (
    echo ОШИБКА: .venv не найден. Сначала запустите install.bat
    pause
    exit /b 1
)

"%VENV_PY%" scripts\download_model.py %*
if errorlevel 1 (
    echo.
    echo ЗАГРУЗКА НЕ УДАЛАСЬ - смотрите вывод выше.
    pause
    exit /b 1
)

echo.
echo Модель готова. В настройках (Ctrl+Shift+O) выберите
echo "Бэкенд перевода" -^> "Локальная модель (NLLB)".
echo.
pause
