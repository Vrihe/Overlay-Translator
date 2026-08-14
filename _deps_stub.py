"""
_deps_stub.py — Stub entry point used by build_deps.spec.

PyInstaller analyses this file to discover and collect all heavy dependencies
(torch, easyocr, scipy, numpy, cv2, PyQt5, …) without involving any
application logic.  This file is NEVER executed at runtime.
"""

# Heavy deps that account for ~95 % of build time and dist size.
# All of these will be collected as individual .pyc files when the
# build_deps.spec is run with --noarchive.
import torch                          # noqa: F401
import torchvision                    # noqa: F401
import easyocr                        # noqa: F401
import scipy                          # noqa: F401
import scipy.ndimage                  # noqa: F401
import scipy.spatial                  # noqa: F401
import scipy.spatial.transform        # noqa: F401
import scipy.special                  # noqa: F401
import numpy                          # noqa: F401
import cv2                            # noqa: F401
import PIL                            # noqa: F401
import PIL.Image                      # noqa: F401
import PIL.ImageDraw                  # noqa: F401
import PIL.ImageFilter                # noqa: F401
import PIL.ImageEnhance               # noqa: F401
import skimage                        # noqa: F401
import skimage.feature                # noqa: F401
import skimage.transform              # noqa: F401
import shapely                        # noqa: F401
import yaml                           # noqa: F401
import langid                         # noqa: F401
import mss                            # noqa: F401
import mss.windows                    # noqa: F401
import optree                         # noqa: F401
from PyQt5.QtWidgets import QApplication   # noqa: F401
from PyQt5.QtCore import QThread           # noqa: F401
from PyQt5.QtGui import QPixmap            # noqa: F401
