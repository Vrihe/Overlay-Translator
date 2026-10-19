# -*- mode: python ; coding: utf-8 -*-
"""
build_app.spec — PyInstaller spec for the app-code layer (fast incremental build).

Part of the layered build system (optimization 2.1).
Run via build.py — do NOT invoke directly with pyinstaller.

All heavy dependencies (onnxruntime, rapidocr, numpy, cv2, PIL …) are listed
in `excludes` so PyInstaller skips re-collecting them.  At runtime they are
found via the regular filesystem import path inside _internal/, where the deps
layer (built by build_deps.spec) placed them as individual .pyc files.

Expected output: dist/TranslatorOverlay/   (tiny — only app code + EXE)
The build.py merge step then copies the cached dep files into this directory.
"""

import sys
from pathlib import Path

# ── sentencepiece workaround ─────────────────────────────────────────────────
# find_binary_dependencies() imports every package in one isolated process, Qt
# bindings first. PyQt5 loads its old msvcp140.dll (14.26) and the sentencepiece
# extension then crashes (0xC0000005). The import only discovers extra DLL search
# dirs, which sentencepiece does not add; its binaries are still collected.
# At runtime main.py loads onnxruntime (newer msvcp140) before Qt, so it is safe.
import PyInstaller.building.build_main
_orig_find_binary_deps = PyInstaller.building.build_main.find_binary_dependencies

def _safe_find_binary_deps(binaries, import_packages, symlink_suppression_patterns):
    filtered = [p for p in import_packages if not p.startswith('sentencepiece')]
    return _orig_find_binary_deps(binaries, filtered, symlink_suppression_patterns)

PyInstaller.building.build_main.find_binary_dependencies = _safe_find_binary_deps

# ─────────────────────────────────────────────────────────────────────────────

block_cipher = None
ROOT = Path(SPECPATH)

icon_path = ROOT / 'assets' / 'icon.ico'
if not icon_path.exists():
    icon_path = ROOT / 'icon.ico'

# ── UPX exclusion list ──────────────────────────────────────────────────────────
_UPX_EXCLUDE = [
    'onnxruntime.dll', 'onnxruntime_providers_shared.dll', 'DirectML.dll',
    'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'vcomp140.dll',
]

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],    # no heavy binaries — provided by the deps cache
    datas=[
        (str(ROOT / 'translate' / 'domain_profiles'), 'translate/domain_profiles'),
    ],
    hiddenimports=[
        # PyQt5 (lightweight, only what app uses)
        'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        # App packages
        'config',
        'settings', 'settings.config_manager',
        'overlay', 'overlay.selector',
        'capture', 'capture.screenshot', 'capture.live_monitor',
        'ocr', 'ocr.engine', 'ocr.hsv_filter',
        'translate', 'translate.llm_client', 'translate.domain_manager',
        'translate.lang_detect', 'translate.error_classification',
        'cache', 'cache.store',
        'ui', 'ui.main_window', 'ui.result_popup',
        'ui.first_run_dialog', 'ui.settings_dialog',
        'history', 'history.history_window',
        'tray', 'tray.tray_icon', 'tray.icon_gen',
        'updater', 'updater.check_update',
        # Lightweight runtime deps
        'keyboard', 'dotenv', 'keyring', 'keyring.backends',
        'urllib.request', 'json', 'webbrowser',
    ],
    excludes=[
        # ── Heavy deps — provided by the deps cache layer ─────────────────────
        'onnxruntime', 'rapidocr', 'pyclipper', 'omegaconf',
        'numpy',
        'cv2',
        'PIL', 'PIL.Image',
        'shapely', 'yaml', 'langid',
        'mss', 'mss.windows',
        'unittest', 'unittest.mock',
        # ── Unused Qt modules ─────────────────────────────────────────────────
        'PyQt5.QtSql', 'PyQt5.QtNetwork', 'PyQt5.QtXml', 'PyQt5.QtBluetooth',
        'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngine', 'PyQt5.QtWebChannel',
        'PyQt5.QtTest', 'PyQt5.QtPrintSupport', 'PyQt5.QtHelp', 'PyQt5.QtDesigner',
        # ── Definitely unused ─────────────────────────────────────────────────
        'torch', 'torchvision', 'easyocr', 'scipy', 'skimage',
        'tensorflow', 'keras', 'openvino', 'jax', 'sklearn', 'h5py', 'grpc',
        'matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook',
    ],
    hookspath=[],
    hooksconfig={},
    # Must run before PyInstaller's PyQt5 hook (custom hooks run first).
    runtime_hooks=[str(ROOT / 'pyi_rth_onnxruntime.py')],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TranslatorOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=_UPX_EXCLUDE,
    name='TranslatorOverlay',
)
