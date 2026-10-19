# -*- mode: python ; coding: utf-8 -*-
"""
build_deps.spec — PyInstaller spec for the heavy-dependencies layer.

Part of the layered build system (optimization 2.1).
Run via build.py — do NOT invoke directly with pyinstaller.

This spec is always invoked with --noarchive so that all Python packages
(onnxruntime, rapidocr, numpy, cv2, PyQt5 …) are laid out as individual
.pyc files inside TranslatorOverlay_deps/_internal/.  The app layer
(build_app.spec) can then find them at runtime via the regular filesystem
import path without needing them in its own PYZ archive.

Expected output: dist/TranslatorOverlay_deps/
"""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_submodules

# ONNX Runtime: onnxruntime.dll, DirectML.dll and the provider bridge DLL.
onnxruntime_binaries = collect_dynamic_libs('onnxruntime')

# RapidOCR: config YAMLs plus only the ONNX models ocr/engine.py uses.  The app
# copies them to the user data dir; a rec model that was not yet downloaded into
# rapidocr/models/ on the build machine is fetched by the app at first run.
_OCR_MODELS = {
    'PP-OCRv6_det_small.onnx',
    'eslav_PP-OCRv5_rec_mobile.onnx',
    'en_PP-OCRv5_rec_mobile.onnx',
}
rapidocr_datas = [
    (src, dst) for src, dst in collect_data_files('rapidocr')
    if not src.endswith('.pyi')
    and (not src.endswith('.onnx') or Path(src).name in _OCR_MODELS)
]

# Only the onnxruntime inference engine is used; the paddle/pytorch/openvino/mnn/
# tensorrt engine modules would drag in frameworks we do not ship.
_UNUSED_ENGINES = ('.paddle', '.pytorch', '.openvino', '.mnn', '.tensorrt')
rapidocr_hiddenimports = collect_submodules(
    'rapidocr', filter=lambda name: not any(e in name for e in _UNUSED_ENGINES)
)

a = Analysis(
    [str(ROOT / '_deps_stub.py')],
    pathex=[str(ROOT)],
    binaries=onnxruntime_binaries,
    datas=rapidocr_datas,
    hiddenimports=[
        'unittest', 'unittest.mock',
        'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'mss', 'mss.windows',
        'onnxruntime', 'onnxruntime.capi', 'onnxruntime.capi._pybind_state',
        'numpy', 'cv2', 'shapely', 'pyclipper', 'yaml', 'omegaconf',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        'langid',
    ] + rapidocr_hiddenimports,
    excludes=[
        # The OCR stack is torch-free; keep a leftover install out of the build.
        'torch', 'torchvision', 'easyocr', 'paddle', 'tensorrt', 'MNN',
        'tensorflow', 'keras', 'openvino', 'jax', 'sklearn', 'h5py', 'grpc',
        'matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,   # place .pyc files individually in _internal/ — required for deps layer
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
