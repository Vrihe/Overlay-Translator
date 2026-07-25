@echo off
echo ============================================
echo   Building Translator Overlay (onedir mode)
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
pyinstaller build.spec --noconfirm %*

echo.
if exist "dist\TranslatorOverlay\TranslatorOverlay.exe" (
    echo ============================================
    echo   BUILD OK (onedir mode)
    echo   Output folder: dist\TranslatorOverlay
    echo   Executable: dist\TranslatorOverlay\TranslatorOverlay.exe
    echo ============================================
    echo.
    echo IMPORTANT:
    echo   1. Copy your .env file into dist\TranslatorOverlay\ (if using local .env)
    echo   2. Package the entire dist\TranslatorOverlay\ folder into a zip archive for release
    echo   3. EasyOCR models will be downloaded on first launch
    echo.
) else (
    echo BUILD FAILED — check the output above.
)

pause
