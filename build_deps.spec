# -*- mode: python ; coding: utf-8 -*-
"""
build_deps.spec — PyInstaller spec for the heavy-dependencies layer.

Part of the layered build system (optimization 2.1).
Run via build.py — do NOT invoke directly with pyinstaller.

This spec is always invoked with --noarchive so that all Python packages
(torch, easyocr, scipy, numpy, cv2, PyQt5 …) are laid out as individual
.pyc files inside TranslatorOverlay_deps/_internal/.  The app layer
(build_app.spec) can then find them at runtime via the regular filesystem
import path without needing them in its own PYZ archive.

Expected output: dist/TranslatorOverlay_deps/
"""

import sys
from pathlib import Path

# ── optree workaround (same as main build.spec) ──────────────────────────────
import PyInstaller.building.build_main
_orig_find_binary_deps = PyInstaller.building.build_main.find_binary_dependencies

def _safe_find_binary_deps(binaries, import_packages, symlink_suppression_patterns):
    filtered = [p for p in import_packages if not p.startswith('optree')]
    return _orig_find_binary_deps(binaries, filtered, symlink_suppression_patterns)

PyInstaller.building.build_main.find_binary_dependencies = _safe_find_binary_deps

# ─────────────────────────────────────────────────────────────────────────────

block_cipher = None
ROOT = Path(SPECPATH)

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_all

torch_binaries      = collect_dynamic_libs('torch')
torchvision_binaries = collect_dynamic_libs('torchvision')

# Targeted torch datas: skip C++ headers, cmake, type stubs, tests (2.2)
torch_datas = [
    (src, dst) for src, dst in collect_data_files('torch')
    if not any(
        skip in src.replace('\\', '/')
        for skip in ('/torch/include/', '/torch/share/', '/torch/test/', '.pyi')
    )
]

# EasyOCR: skip bundled .pt weights (downloaded to ~/.EasyOCR/ at first run)
easyocr_datas = [
    (src, dst) for src, dst in collect_data_files('easyocr')
    if not src.endswith('.pt')
]

optree_datas, optree_binaries, optree_hiddenimports = collect_all('optree')

a = Analysis(
    [str(ROOT / '_deps_stub.py')],
    pathex=[str(ROOT)],
    binaries=torch_binaries + torchvision_binaries + optree_binaries,
    datas=torch_datas + easyocr_datas + optree_datas,
    hiddenimports=[
        'unittest', 'unittest.mock',
        'optree', 'optree._C',
        'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'mss', 'mss.windows',
        'easyocr', 'easyocr.easyocr', 'easyocr.model', 'easyocr.craft',
        'easyocr.detection', 'easyocr.recognition', 'easyocr.utils',
        'torch', 'torch._C', 'torch._C._nn', 'torch._C._fft',
        'torch._C._linalg', 'torch.distributions',
        'torchvision', 'torchvision.ops',
        'numpy', 'scipy', 'scipy.ndimage', 'scipy.spatial',
        'scipy.spatial.transform', 'scipy.special',
        'skimage', 'skimage.feature', 'skimage.transform',
        'cv2', 'shapely', 'yaml',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        'langid',
    ] + optree_hiddenimports,
    excludes=[
        'tensorflow', 'keras', 'openvino', 'jax', 'sklearn', 'h5py', 'grpc',
        'matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook',
        'scipy.optimize', 'scipy.stats', 'scipy.signal', 'scipy.io.matlab',
        'skimage.io', 'skimage.viewer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / 'pyi_rth_torch_dll.py')],
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
    name='deps_stub',        # placeholder name; this EXE is never distributed
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # never UPX the deps stub EXE
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TranslatorOverlay_deps',   # output → dist/TranslatorOverlay_deps/
)
