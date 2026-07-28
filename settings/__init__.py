"""
settings — secure API key storage (keyring) + JSON config manager.

Public surface re-exported here so ``import settings`` keeps working
everywhere:

  settings.get_api_key(provider)
  settings.set_api_key(provider, key)
  settings.delete_api_key(provider)
  settings.has_any_key()

  from settings import config_manager
  config_manager.load_config()
  config_manager.save_config(cfg)
  config_manager.get(key)
  config_manager.set_value(key, value)
"""

try:
    import keyring
    _HAS_KEYRING = True
except ImportError:
    keyring = None
    _HAS_KEYRING = False

from settings import config_manager            # noqa: F401

# ── Keyring-based API key storage ────────────────────────

_SERVICE = "OverlayTranslator"

_KEY_OPENROUTER = "openrouter_api_key"
_KEY_ANTHROPIC = "anthropic_api_key"

_PROVIDER_KEYS = {
    "openrouter": _KEY_OPENROUTER,
    "anthropic": _KEY_ANTHROPIC,
}


def get_api_key(provider: str) -> str | None:
    """Retrieve the API key for *provider* from keyring."""
    if not _HAS_KEYRING:
        return None
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        return None
    try:
        value = keyring.get_password(_SERVICE, keyname)
        return value if value else None
    except Exception:
        return None


def set_api_key(provider: str, key: str) -> None:
    """Store the API key for *provider* in keyring."""
    if not _HAS_KEYRING:
        raise RuntimeError("keyring is not installed — cannot store API keys securely.")
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        raise ValueError(f"Unknown provider: {provider!r}")
    keyring.set_password(_SERVICE, keyname, key)


def delete_api_key(provider: str) -> None:
    """Remove the stored API key for *provider* from keyring."""
    if not _HAS_KEYRING:
        return
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        return
    try:
        keyring.delete_password(_SERVICE, keyname)
    except Exception:
        pass


def has_any_key() -> bool:
    """Return True if at least one API key is stored in keyring."""
    return any(get_api_key(p) for p in _PROVIDER_KEYS)


def get_primary_provider() -> str:
    """Return configured primary provider name ('openrouter' or 'anthropic')."""
    val = config_manager.get("primary_provider")
    if val in ("openrouter", "anthropic"):
        return val
    return "openrouter"


def save_primary_provider(provider: str) -> None:
    """Save primary provider choice."""
    if provider in ("openrouter", "anthropic"):
        config_manager.set_value("primary_provider", provider)


def is_fallback_enabled() -> bool:
    """Return whether automatic fallback to secondary provider is enabled."""
    val = config_manager.get("enable_fallback")
    return bool(val) if val is not None else True


def set_fallback_enabled(enabled: bool) -> None:
    """Save fallback enabled setting."""
    config_manager.set_value("enable_fallback", bool(enabled))

