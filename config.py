"""
Translator Overlay — global configuration.

All tunables are centralised here.  Sensitive values (API keys) are
loaded from the ``.env`` file via python-dotenv.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

_PROJECT_DIR = Path(__file__).resolve().parent

# ─── Hotkey ──────────────────────────────────────────────
# Combo string understood by the `keyboard` library.
HOTKEY = os.environ.get("HOTKEY", "ctrl+shift+t")

# ─── Tesseract OCR ──────────────────────────────────────
# Path to the Tesseract executable on Windows.
# Adjust if you installed Tesseract to a non-default location.
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

# OCR language(s). Use '+' to combine, e.g. "eng+rus"
OCR_LANG = os.environ.get("OCR_LANG", "eng")

# ─── Translation ────────────────────────────────────────
# Source / target languages (ISO 639-1 or full name)
SOURCE_LANG = os.environ.get("SOURCE_LANG", "en")
TARGET_LANG = os.environ.get("TARGET_LANG", "ru")

# ─── Overlay UI ─────────────────────────────────────────
OVERLAY_OPACITY = float(os.environ.get("OVERLAY_OPACITY", "0.85"))
OVERLAY_FONT_SIZE = int(os.environ.get("OVERLAY_FONT_SIZE", "14"))

# ─── Popup ──────────────────────────────────────────────
# Auto-close timeout for the result popup (seconds).
POPUP_TIMEOUT_SEC = int(os.environ.get("POPUP_TIMEOUT_SEC", "10"))

# ─── Cache ──────────────────────────────────────────────
CACHE_DIR = os.environ.get("CACHE_DIR", str(_PROJECT_DIR / "cache"))
CACHE_MAX_ITEMS = int(os.environ.get("CACHE_MAX_ITEMS", "500"))

# ─── Logging ────────────────────────────────────────────
LOG_DIR = os.environ.get("LOG_DIR", str(_PROJECT_DIR / "logs"))
LOG_FILE = os.path.join(LOG_DIR, "translator.log")
