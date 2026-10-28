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


def _get_user_data_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            path = Path(appdata) / "translator-overlay"
            path.mkdir(parents=True, exist_ok=True)
            return path
    path = Path.home() / ".config" / "translator-overlay"
    path.mkdir(parents=True, exist_ok=True)
    return path


# A module-level literal so pyproject.toml (setuptools) and build.py can read
# the version without importing config.
APP_VERSION = "1.4.1"


class _LiveConfig:
    """Descriptor-based config so module-level reads always
    reflect the latest settings.json values."""

    # ── Dynamic (from settings.json) ─────────────────────

    @property
    def HOTKEY(self):
        return _cfg("hotkey")

    @HOTKEY.setter
    def HOTKEY(self, value):
        from settings.config_manager import set_value

        set_value("hotkey", value)

    @property
    def LIVE_INTERVAL_SEC(self):
        """Live monitoring: seconds between two checks of the region."""
        return _cfg("live_interval_sec")

    @LIVE_INTERVAL_SEC.setter
    def LIVE_INTERVAL_SEC(self, value):
        from settings.config_manager import set_value

        set_value("live_interval_sec", value)

    @property
    def LIVE_SENSITIVITY(self):
        """Live monitoring: "high" | "medium" | "low" — how small a change counts."""
        return _cfg("live_sensitivity")

    @LIVE_SENSITIVITY.setter
    def LIVE_SENSITIVITY(self, value):
        from settings.config_manager import set_value

        set_value("live_sensitivity", value)

    @property
    def SETTINGS_HOTKEY(self):
        """Opens the settings; the SETTINGS_HOTKEY env var overrides settings.json."""
        return os.environ.get("SETTINGS_HOTKEY") or _cfg("settings_hotkey")

    @SETTINGS_HOTKEY.setter
    def SETTINGS_HOTKEY(self, value):
        from settings.config_manager import set_value

        set_value("settings_hotkey", value)

    @property
    def ENABLE_OCR_PREVIEW(self):
        return _cfg("enable_ocr_preview")

    @ENABLE_OCR_PREVIEW.setter
    def ENABLE_OCR_PREVIEW(self, value):
        from settings.config_manager import set_value

        set_value("enable_ocr_preview", value)

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
    def TRANSLATION_BACKEND(self):
        """Which translator runs: "google" (default), "api" (cloud LLM), "deepl", "azure", "nllb"."""
        return _cfg("translation_backend")

    @TRANSLATION_BACKEND.setter
    def TRANSLATION_BACKEND(self, value):
        from settings.config_manager import set_value

        set_value("translation_backend", value)

    @property
    def NLLB_MODEL_PATH(self):
        """Explicit CTranslate2 model directory; "" means auto-discover."""
        return _cfg("nllb_model_path")

    @NLLB_MODEL_PATH.setter
    def NLLB_MODEL_PATH(self, value):
        from settings.config_manager import set_value

        set_value("nllb_model_path", value)

    @property
    def NLLB_DEVICE(self):
        """NLLB device: 'auto' (NVIDIA GPU when cuBLAS is found, else CPU) or 'cpu'."""
        return _cfg("nllb_device")

    @NLLB_DEVICE.setter
    def NLLB_DEVICE(self, value):
        from settings.config_manager import set_value

        set_value("nllb_device", value)

    @property
    def OCR_GPU_MODE(self):
        """OCR device mode: 'auto' (DirectML GPU when available) or 'cpu'; legacy 'gpu' = 'auto'."""
        return _cfg("ocr_gpu_mode")

    @OCR_GPU_MODE.setter
    def OCR_GPU_MODE(self, value):
        from settings.config_manager import set_value

        set_value("ocr_gpu_mode", value)

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

    @property
    def SOURCE_LANG(self):
        return _cfg("source_language")

    @SOURCE_LANG.setter
    def SOURCE_LANG(self, value):
        from settings.config_manager import set_value

        set_value("source_language", value)

    @property
    def NOTIFICATION_TYPE(self):
        return _cfg("notification_type")

    @NOTIFICATION_TYPE.setter
    def NOTIFICATION_TYPE(self, value):
        from settings.config_manager import set_value

        set_value("notification_type", value)

    @property
    def OCR_LANGUAGES(self):
        return _cfg("ocr_languages")

    @OCR_LANGUAGES.setter
    def OCR_LANGUAGES(self, value):
        from settings.config_manager import set_value

        set_value("ocr_languages", value)

    @property
    def ACTIVE_DOMAIN(self):
        return _cfg("active_domain")

    @ACTIVE_DOMAIN.setter
    def ACTIVE_DOMAIN(self, value):
        from settings.config_manager import set_value

        set_value("active_domain", value)

    @property
    def FIRST_RUN_DONE(self):
        return bool(_cfg("first_run_done"))

    @FIRST_RUN_DONE.setter
    def FIRST_RUN_DONE(self, value):
        from settings.config_manager import set_value

        set_value("first_run_done", bool(value))

    @property
    def ENABLE_STREAMING(self):
        return _cfg("enable_streaming")

    @ENABLE_STREAMING.setter
    def ENABLE_STREAMING(self, value):
        from settings.config_manager import set_value

        set_value("enable_streaming", value)

    @property
    def COMPACT_PROMPT(self):
        return _cfg("compact_prompt")

    @COMPACT_PROMPT.setter
    def COMPACT_PROMPT(self, value):
        from settings.config_manager import set_value

        set_value("compact_prompt", value)

    @property
    def LLM_MAX_TOKENS(self):
        return _cfg("llm_max_tokens")

    @LLM_MAX_TOKENS.setter
    def LLM_MAX_TOKENS(self, value):
        from settings.config_manager import set_value

        set_value("llm_max_tokens", value)

    @property
    def POPUP_SIZE(self):
        return _cfg("popup_size")

    @POPUP_SIZE.setter
    def POPUP_SIZE(self, value):
        from settings.config_manager import set_value

        set_value("popup_size", value)

    @property
    def UI_THEME(self):
        return _cfg("ui_theme")

    @UI_THEME.setter
    def UI_THEME(self, value):
        from settings.config_manager import set_value

        set_value("ui_theme", value)

    # ── Static (from .env / hardcoded) ───────────────────

    MAX_RETRIES_PER_PROVIDER = int(os.environ.get("MAX_RETRIES_PER_PROVIDER", "2"))
    RETRY_BACKOFF_BASE_SEC = float(os.environ.get("RETRY_BACKOFF_BASE_SEC", "1.0"))
    OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "poolside/laguna-s-2.1:free")
    # LLM_MODEL is an OpenRouter id; Anthropic (primary or fallback) needs its own.
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
    ANTHROPIC_DETECT_MODEL = os.environ.get("ANTHROPIC_DETECT_MODEL", "claude-haiku-5-5")

    APP_VERSION = APP_VERSION
    GITHUB_REPO = os.environ.get("GITHUB_REPO", "Vrihe/Overlay-Translator")

    # ─── Local NLLB model on the Hugging Face Hub ───────────
    # The single place that pins which model build the project uses; read by
    # scripts/download_model.py. The revision is a full commit SHA, not a tag:
    # a tag can be moved to other weights later, a commit cannot. To move everyone
    # to a new build, tag it in the HF repo and put that tag's commit SHA here.
    NLLB_HF_REPO_ID = os.environ.get("NLLB_HF_REPO_ID", "Alhite/overlay-translator-nllb-int8")
    NLLB_HF_REVISION = os.environ.get("NLLB_HF_REVISION", "0e37166ae8c6ceb2a8f2560fc41b780e5bd41f3d")  # tag v0-base
    # Expand English game-chat terms before local translation (translate/chat_glossary.py).
    NLLB_GLOSSARY = os.environ.get("NLLB_GLOSSARY", "1").lower() not in ("0", "false", "no")

    _PROJECT_DIR = _PROJECT_DIR

    OCR_USE_HSV_FILTER = os.environ.get("OCR_USE_HSV_FILTER", "").lower() in ("1", "true")

    # ─── OCR Engine (RapidOCR; EASYOCR_* env names kept for existing .env files) ──
    _LANGS_RAW = os.environ.get("EASYOCR_LANGS", "ru,en")
    EASYOCR_LANGS = [lang.strip() for lang in _LANGS_RAW.split(",") if lang.strip()]
    EASYOCR_GPU = os.environ.get("EASYOCR_GPU", "auto")
    EASYOCR_CONFIDENCE_THRESHOLD = float(os.environ.get("EASYOCR_CONFIDENCE_THRESHOLD", "0.25"))

    USER_DATA_DIR = _get_user_data_dir()
    CACHE_DIR = os.environ.get("CACHE_DIR", str(USER_DATA_DIR / "cache"))
    CACHE_MAX_ITEMS = int(os.environ.get("CACHE_MAX_ITEMS", "500"))

    LOG_DIR = os.environ.get("LOG_DIR", str(USER_DATA_DIR / "logs"))
    LOG_FILE = os.path.join(LOG_DIR, "translator.log")
    # Captured screen text stays out of the logs unless explicitly enabled for debugging
    # (translate/privacy.py).
    LOG_TEXT = os.environ.get("OVERLAY_LOG_TEXT", "").lower() in ("1", "true", "yes")


# Replace this module in sys.modules with the _LiveConfig instance
# so that  `import config; config.HOTKEY`  works with properties.
sys.modules[__name__] = _LiveConfig()
