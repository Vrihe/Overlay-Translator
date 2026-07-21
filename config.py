"""
Translator Overlay — global configuration.

Static defaults (paths, env-only values) live here.
Dynamic user preferences (language, model, hotkey, etc.) are loaded
from ``settings.json`` via ``settings.config_manager``.

Sensitive values (API keys) are loaded from ``.env`` via python-dotenv
or from the OS keyring via the ``settings`` package.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# When frozen by PyInstaller, sys.executable is the .exe path.
if getattr(sys, 'frozen', False):
    _PROJECT_DIR = Path(sys.executable).resolve().parent
else:
    _PROJECT_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file next to the app.
load_dotenv(_PROJECT_DIR / '.env')

# ── Dynamic settings (from settings.json) ────────────────
# Imported lazily on first access so that this module can be
# imported before the settings package is fully initialised.

def _cfg(key: str):
    """Helper: read a value from the JSON config manager."""
    from settings.config_manager import get
    return get(key)


class _LiveConfig:
    """Descriptor-based config so module-level reads always
    reflect the latest settings.json values."""

    # ── Dynamic (from settings.json) ─────────────────────

    @property
    def HOTKEY(self):
        return _cfg("hotkey")

    @property
    def TARGET_LANG(self):
        return _cfg("target_language")

    @TARGET_LANG.setter
    def TARGET_LANG(self, value):
        from settings.config_manager import set_value
        set_value("target_language", value)

    @property
    def TRANSLATION_ENGINE(self):
        return _cfg("translation_engine")

    @TRANSLATION_ENGINE.setter
    def TRANSLATION_ENGINE(self, value):
        from settings.config_manager import set_value
        set_value("translation_engine", value)

    @property
    def LLM_MODEL(self):
        return _cfg("llm_model")

    @LLM_MODEL.setter
    def LLM_MODEL(self, value):
        from settings.config_manager import set_value
        set_value("llm_model", value)

    @property
    def POPUP_TIMEOUT_SEC(self):
        return _cfg("popup_timeout_sec")

    @POPUP_TIMEOUT_SEC.setter
    def POPUP_TIMEOUT_SEC(self, value):
        from settings.config_manager import set_value
        set_value("popup_timeout_sec", value)

    # ── Static (from .env / hardcoded) ───────────────────

    SETTINGS_HOTKEY = os.environ.get("SETTINGS_HOTKEY", "ctrl+shift+o")

    TESSERACT_CMD = os.environ.get(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )

    OCR_LANG = os.environ.get("OCR_LANG", "eng")
    OCR_USE_HSV_FILTER = os.environ.get("OCR_USE_HSV_FILTER", "").lower() in ("1", "true")

    SOURCE_LANG = os.environ.get("SOURCE_LANG", "en")

    OVERLAY_OPACITY = float(os.environ.get("OVERLAY_OPACITY", "0.85"))
    OVERLAY_FONT_SIZE = int(os.environ.get("OVERLAY_FONT_SIZE", "14"))

    CACHE_DIR = os.environ.get("CACHE_DIR", str(_PROJECT_DIR / "cache"))
    CACHE_MAX_ITEMS = int(os.environ.get("CACHE_MAX_ITEMS", "500"))

    LOG_DIR = os.environ.get("LOG_DIR", str(_PROJECT_DIR / "logs"))
    LOG_FILE = os.path.join(LOG_DIR, "translator.log")


# Replace this module in sys.modules with the _LiveConfig instance
# so that  `import config; config.HOTKEY`  works with properties.
sys.modules[__name__] = _LiveConfig()
