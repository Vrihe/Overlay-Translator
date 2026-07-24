"""
settings/config_manager.py — persistent JSON-based configuration.

Stores user preferences in ``settings.json`` next to the application.
Falls back to sane defaults when the file doesn't exist or is corrupted.

Stored keys:
  • target_language       — ISO 639-1 code (default "ru")
  • translation_engine    — "llm_text" | "llm_vision" | "api"
  • llm_model             — model identifier for OpenRouter / Anthropic
  • hotkey                — keyboard combo string
  • popup_timeout_sec     — auto-close delay for the result popup
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

# ── Resolve the directory where settings.json lives ──────

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

_USER_DATA_DIR = _get_user_data_dir()
_CONFIG_FILE = _USER_DATA_DIR / "settings.json"

# Migrate legacy settings.json if present next to app
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).resolve().parent
else:
    _APP_DIR = Path(__file__).resolve().parent.parent   # project root

_OLD_CONFIG_FILE = _APP_DIR / "settings.json"
if not _CONFIG_FILE.exists() and _OLD_CONFIG_FILE.exists():
    try:
        shutil.copy2(_OLD_CONFIG_FILE, _CONFIG_FILE)
    except Exception:
        pass

# ── Default values ───────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "source_language": "auto",
    "target_language": "ru",
    "translation_engine": "llm_text",     # "llm_text" | "llm_vision" | "api"
    "llm_model": "openai/gpt-oss-20b:free",
    "hotkey": "ctrl+shift+r",
    "popup_timeout_sec": 10,
    "notification_type": "popup",          # "popup" | "windows_toast"
    "ocr_languages": ["en", "ru"],
}

# ── In-memory cache ──────────────────────────────────────
# Loaded once, written on every save_config().

_cache: dict[str, Any] | None = None


def _ensure_loaded() -> dict[str, Any]:
    global _cache
    if _cache is None:
        _cache = load_config()
    return _cache


# ── Public API ───────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """Read ``settings.json`` and return a merged dict (defaults + saved).

    If the file doesn't exist or is malformed, returns a copy of DEFAULTS
    and writes a fresh file to disk.
    """
    global _cache
    cfg = dict(DEFAULTS)

    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except (json.JSONDecodeError, OSError):
            pass  # corrupted → fall through to defaults

    _cache = cfg
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """Write *cfg* to ``settings.json`` (atomic-ish via write + flush).

    Only known keys from DEFAULTS are persisted; unknown keys are ignored
    to keep the file tidy.
    """
    global _cache
    # Keep only recognised keys.
    filtered = {k: cfg[k] for k in DEFAULTS if k in cfg}
    _cache = dict(DEFAULTS)
    _cache.update(filtered)

    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2, ensure_ascii=False)


def get(key: str) -> Any:
    """Return a single config value by *key*, loading from disk if needed."""
    return _ensure_loaded().get(key, DEFAULTS.get(key))


def set_value(key: str, value: Any) -> None:
    """Update a single value and persist immediately."""
    cfg = _ensure_loaded()
    cfg[key] = value
    save_config(cfg)
