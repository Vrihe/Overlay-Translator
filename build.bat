@echo off
echo ============================================
echo   Building Translator Overlay .exe
echo ============================================
echo.

:: Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

:: Run the build
echo Running PyInstaller...
pyinstaller translator.spec --clean

echo.
if exist "dist\TranslatorOverlay.exe" (
    echo ============================================
    echo   BUILD OK
    echo   Output: dist\TranslatorOverlay.exe
    echo ============================================
    echo.
    echo IMPORTANT:
    echo   1. Copy your .env file next to the .exe
    echo   2. EasyOCR models will be downloaded on first launch
    echo.
) else (
    echo BUILD FAILED — check the output above.
)

pause
