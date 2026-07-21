"""
Translator Overlay — global configuration.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ─── Hotkey ──────────────────────────────────────────────
HOTKEY = "ctrl+shift+t"

# ─── Tesseract OCR ──────────────────────────────────────
# Path to the Tesseract executable on Windows.
# Adjust if you installed Tesseract to a non-default location.
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# OCR language(s). Use '+' to combine, e.g. "eng+rus"
OCR_LANG = "eng"

# ─── Translation ────────────────────────────────────────
# Source / target languages (ISO 639-1)
SOURCE_LANG = "en"
TARGET_LANG = "ru"

# ─── Overlay UI ─────────────────────────────────────────
OVERLAY_OPACITY = 0.85
OVERLAY_FONT_SIZE = 14

# ─── Cache ──────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
CACHE_MAX_ITEMS = 500
