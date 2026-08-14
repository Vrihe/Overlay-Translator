# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file (build.spec) for Translator Overlay (onedir mode).

Build command:
    python build.py
    or: pyinstaller build.spec --noconfirm

Optimizations applied:
  2.2 — targeted torch datas (exclude headers/stubs/tests)
  3.4 — partial UPX: enabled globally, torch DLLs excluded to avoid WinError 1114
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

# ── 2.2: Targeted torch datas — exclude C++ headers, type stubs, tests ─────
# collect_data_files('torch') pulls in thousands of files including .pyi stubs,
# CMakeLists, include/ headers and test data — none of which are needed at runtime.
# Filtering them out cuts PyInstaller analysis time by 30-40% and dist size by 50-200 MB.
_raw_torch_datas = collect_data_files('torch')
torch_datas = [
    (src, dst) for src, dst in _raw_torch_datas
    if not any(
        skip in src.replace('\\', '/')
        for skip in (
            '/torch/include/',   # C++ headers — build-time only
            '/torch/share/',     # CMake / pkgconfig — not needed at runtime
            '/torch/test/',      # test suite
            '.pyi',              # type stubs — not needed at runtime
        )
    )
]

# Exclude EasyOCR .pt model weights — they are downloaded to ~/.EasyOCR/ at first run
_raw_easyocr_datas = collect_data_files('easyocr')
easyocr_datas = [
    (src, dst) for src, dst in _raw_easyocr_datas
    if not src.endswith('.pt')
]

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
        # OCR & PyTorch & Image Processing
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
        # Application packages
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
        # System & network helpers
        'dotenv',
        'keyring',
        'keyring.backends',
        'urllib.request',
        'json',
        'webbrowser',
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
        # Unused Qt modules — not needed for this app's UI stack
        'PyQt5.QtSql',
        'PyQt5.QtNetwork',
        'PyQt5.QtXml',
        'PyQt5.QtBluetooth',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebChannel',
        'PyQt5.QtTest',
        'PyQt5.QtPrintSupport',
        'PyQt5.QtHelp',
        'PyQt5.QtDesigner',
        # Heavy optional scipy components not used by easyocr core
        'scipy.optimize',
        'scipy.stats',
        'scipy.signal',
        'scipy.io.matlab',
        # skimage.io / skimage.viewer: NOT excluded — easyocr imports them at init
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
    upx=True,
    console=False,            # Windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

# ── 3.4: Partial UPX — compress PyQt5/PIL/OpenCV, skip torch DLLs ───────────
# Torch DLLs (c10.dll, torch_cpu.dll, etc.) crash at init if UPX-compressed
# because UPX modifies their PE header in a way that breaks Windows DLL loading.
# All other binaries (PyQt5, Pillow, OpenCV, numpy) compress safely: ~15-30% size reduction.
_UPX_EXCLUDE = [
    # PyTorch core — MUST NOT be compressed
    'torch_cpu.dll',
    'c10.dll',
    'torch.dll',
    'libiomp5md.dll',
    'fbgemm.dll',
    'asmjit.dll',
    'uv.dll',
    # MSVC / OpenMP runtimes — compress at risk of CRT conflict
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'msvcp140.dll',
    'vcomp140.dll',
    # torchvision
    'torchvision.dll',
]

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
