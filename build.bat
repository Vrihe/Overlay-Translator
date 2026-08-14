@echo off
echo ============================================================
echo   Translator Overlay ^| Layered Build  (optimization 2.1)
echo ============================================================
echo.
echo   FIRST BUILD (or after --clean):
echo     Phase 1 - Heavy deps  : 10-15 min  (cached afterwards)
echo     Phase 2 - App code    :  1-3  min
echo.
echo   SUBSEQUENT BUILDS (deps unchanged):
echo     Phase 1 - Restore cache : seconds
echo     Phase 2 - App code      : 1-3 min
echo     TOTAL: ~2-3 min instead of 15-20 min
echo.

:: Install PyInstaller if not present
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

:: Run the layered build orchestrator, forwarding all arguments (%*)
:: Examples:
::   build.bat           — smart build (fast if cache exists)
::   build.bat --clean   — force full rebuild, refresh cache
::   build.bat --cache-info — print fingerprint and exit
python build.py %*

echo.
if exist "dist\TranslatorOverlay\TranslatorOverlay.exe" (
    echo ============================================================
    echo   BUILD OK
    echo   Output  : dist\TranslatorOverlay\
    echo   EXE     : dist\TranslatorOverlay\TranslatorOverlay.exe
    echo ============================================================
    echo.
    echo NOTES:
    echo   1. Copy your .env file into dist\TranslatorOverlay\ ^(if using local .env^)
    echo   2. Package the entire dist\TranslatorOverlay\ folder for release
    echo   3. EasyOCR models are downloaded on first launch
    echo   4. Deps cache lives in _build_cache\  (gitignored, rebuild with --clean)
    echo.
) else (
    echo BUILD FAILED - check the output above.
)

pause
