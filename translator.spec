# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Translator Overlay (onedir mode).

Build command:
    pyinstaller translator.spec --noconfirm
"""

import os
import sys
from pathlib import Path

# Prevent PyInstaller's isolated child scanner from crashing when importing optree C-extension
import PyInstaller.building.build_main
_orig_find_binary_deps = PyInstaller.building.build_main.find_binary_dependencies

def _safe_find_binary_deps(binaries, import_packages, symlink_suppression_patterns):
    filtered_packages = [p for p in import_packages if not p.startswith('optree')]
    return _orig_find_binary_deps(binaries, filtered_packages, symlink_suppression_patterns)

PyInstaller.building.build_main.find_binary_dependencies = _safe_find_binary_deps

block_cipher = None

ROOT = Path(SPECPATH)

icon_path = ROOT / 'assets' / 'icon.ico'
if not icon_path.exists():
    icon_path = ROOT / 'icon.ico'

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_all

torch_binaries = collect_dynamic_libs('torch')
torchvision_binaries = collect_dynamic_libs('torchvision')
torch_datas = collect_data_files('torch')
easyocr_datas = collect_data_files('easyocr')

optree_datas, optree_binaries, optree_hiddenimports = collect_all('optree')

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=torch_binaries + torchvision_binaries + optree_binaries,
    datas=[
        (str(ROOT / 'translate' / 'domain_profiles'), 'translate/domain_profiles'),
    ] + torch_datas + easyocr_datas + optree_datas,
    hiddenimports=[
        # Standard library modules required by PyTorch
        'unittest',
        'unittest.mock',
        'optree',
        'optree._C',
        # PyQt5 plugins
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        # Screen capture
        'mss',
        'mss.windows',
        # EasyOCR & dependencies
        'easyocr',
        'easyocr.easyocr',
        'easyocr.model',
        'easyocr.craft',
        'easyocr.detection',
        'easyocr.recognition',
        'easyocr.utils',
        'torch',
        'torch._C',
        'torch._C._nn',
        'torch._C._fft',
        'torch._C._linalg',
        'torch.distributions',
        'torchvision',
        'torchvision.ops',
        'numpy',
        'scipy',
        'scipy.ndimage',
        'scipy.spatial',
        'scipy.spatial.transform',
        'scipy.special',
        'skimage',
        'skimage.feature',
        'skimage.transform',
        'cv2',
        'shapely',
        'yaml',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFilter',
        'PIL.ImageEnhance',
        # Our own packages
        'config',
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
        'translate.domain_manager',
        'translate.lang_detect',
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
        # dotenv & keyring
        'dotenv',
        'keyring',
        'keyring.backends',
        'langid',
    ] + optree_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / 'pyi_rth_torch_dll.py')],
    excludes=[
        'tensorflow',
        'keras',
        'openvino',
        'jax',
        'sklearn',
        'h5py',
        'grpc',
        'matplotlib',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
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
    [],                       # Onedir mode: no binaries inside EXE
    exclude_binaries=True,
    name='TranslatorOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # Windowed mode
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
    upx=False,
    upx_exclude=[],
    name='TranslatorOverlay',
)
