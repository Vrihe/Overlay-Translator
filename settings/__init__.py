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
