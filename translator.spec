# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Translator Overlay.

Build command:
    pyinstaller translator.spec

Output:
    dist/TranslatorOverlay.exe  (single file, no console)
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Include .env if it exists (user's config — optional)
        # (str(ROOT / '.env'), '.'),
    ],
    hiddenimports=[
        # PyQt5 plugins that PyInstaller sometimes misses
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        # mss platform backends
        'mss',
        'mss.windows',
        # Our own packages
        'overlay',
        'overlay.selector',
        'capture',
        'capture.screenshot',
        'ocr',
        'ocr.engine',
        'translate',
        'translate.llm_client',
        'cache',
        'cache.store',
        'ui',
        'ui.result_popup',
        'tray',
        'tray.tray_icon',
        'tray.icon_gen',
        # dotenv
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'matplotlib', 'numpy',
        'scipy', 'pandas',
        'pytest', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TranslatorOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # ← NO console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',  # ← uncomment when you have an .ico file
)
