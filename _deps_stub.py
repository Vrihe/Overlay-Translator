"""
_deps_stub.py — Stub entry point used by build_deps.spec.

PyInstaller analyses this file to discover and collect all heavy dependencies
(onnxruntime, rapidocr, numpy, cv2, PyQt5, …) without involving any
application logic.  This file is NEVER executed at runtime.
"""

# Heavy deps that account for ~95 % of build time and dist size.
# All of these will be collected as individual .pyc files when the
# build_deps.spec is run with --noarchive.
import onnxruntime                    # noqa: F401
import rapidocr                       # noqa: F401
import pyclipper                      # noqa: F401
import omegaconf                      # noqa: F401
import numpy                          # noqa: F401
import cv2                            # noqa: F401
import PIL                            # noqa: F401
import PIL.Image                      # noqa: F401
import PIL.ImageDraw                  # noqa: F401
import PIL.ImageFilter                # noqa: F401
import PIL.ImageEnhance               # noqa: F401
import shapely                        # noqa: F401
import yaml                           # noqa: F401
import langid                         # noqa: F401
import mss                            # noqa: F401
import mss.windows                    # noqa: F401
from PyQt5.QtWidgets import QApplication   # noqa: F401
from PyQt5.QtCore import QThread           # noqa: F401
from PyQt5.QtGui import QPixmap            # noqa: F401
