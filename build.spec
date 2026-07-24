# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file (build.spec) for Translator Overlay.

Build command:
    pyinstaller build.spec --clean
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

icon_path = ROOT / 'assets' / 'icon.ico'
if not icon_path.exists():
    icon_path = ROOT / 'icon.ico'

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # (str(ROOT / '.env'), '.'),
    ],
    hiddenimports=[
        # PyQt5 plugins
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        # Screen capture
        'mss',
        'mss.windows',
        # OCR & Deep Learning
        'easyocr',
        'torch',
        'torchvision',
        'numpy',
        'PIL',
        'PIL.Image',
        # Application packages
        'settings',
        'settings.config_manager',
        'overlay',
        'overlay.selector',
        'capture',
        'capture.screenshot',
        'ocr',
        'ocr.engine',
        'ocr.hsv_filter',
        'translate',
        'translate.llm_client',
        'cache',
        'cache.store',
        'ui',
        'ui.main_window',
        'ui.result_popup',
        'ui.first_run_dialog',
        'ui.settings_dialog',
        'history',
        'history.history_window',
        'tray',
        'tray.tray_icon',
        'tray.icon_gen',
        'updater',
        'updater.check_update',
        # System & network helpers
        'dotenv',
        'keyring',
        'keyring.backends',
        'urllib.request',
        'json',
        'webbrowser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tensorflow',
        'keras',
        'optree',
        'openvino',
        'jax',
        'sklearn',
        'h5py',
        'grpc',
        'tensorboard',
        'matplotlib',
        'scipy',
        'pandas',
        'tkinter', '_tkinter',
        'pytest', 'unittest',
        'IPython', 'jupyter',
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
    console=False,            # Windowed mode (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)
