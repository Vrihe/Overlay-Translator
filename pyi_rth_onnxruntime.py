"""
pyi_rth_onnxruntime.py — PyInstaller runtime hook: load onnxruntime before Qt.

Custom runtime hooks run before PyInstaller's own. Its PyQt5 hook imports
PyQt5.QtCore (to write an embedded qt.conf), which loads PyQt5's old
MSVCP140.dll / MSVCP140_1.dll (14.26) from Qt5\\bin. onnxruntime needs >= 14.40
and then fails with "DLL initialization routine failed". Imported here first, it
binds to the current runtime that build.py copies to the _internal root.
main.py does the same for source runs.
"""

try:
    import onnxruntime  # noqa: F401
except Exception:
    pass  # main.py / ocr.engine log the failure and keep OCR disabled
