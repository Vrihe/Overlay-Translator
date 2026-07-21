"""
settings.py — secure API key storage via keyring.

Wraps the ``keyring`` library to store and retrieve API keys from
the OS credential store (Windows Credential Locker, macOS Keychain,
or the Secret Service API on Linux).

Priority when resolving an API key:
  1. keyring  (set via FirstRunDialog / SettingsDialog)
  2. environment variable  (for dev workflow with .env)
"""

import keyring

_SERVICE = "OverlayTranslator"

# Keyring key names for each supported provider.
_KEY_OPENROUTER = "openrouter_api_key"
_KEY_ANTHROPIC = "anthropic_api_key"

_PROVIDER_KEYS = {
    "openrouter": _KEY_OPENROUTER,
    "anthropic": _KEY_ANTHROPIC,
}


def get_api_key(provider: str) -> str | None:
    """Retrieve the API key for *provider* from keyring.

    Parameters
    ----------
    provider : str
        ``"openrouter"`` or ``"anthropic"``.

    Returns
    -------
    str or None
        The stored key, or ``None`` if not set.
    """
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        return None
    try:
        value = keyring.get_password(_SERVICE, keyname)
        # keyring may return an empty string on some backends.
        return value if value else None
    except Exception:
        return None


def set_api_key(provider: str, key: str) -> None:
    """Store the API key for *provider* in keyring.

    Parameters
    ----------
    provider : str
        ``"openrouter"`` or ``"anthropic"``.
    key : str
        The API key value.
    """
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        raise ValueError(f"Unknown provider: {provider!r}")
    keyring.set_password(_SERVICE, keyname, key)


def delete_api_key(provider: str) -> None:
    """Remove the stored API key for *provider* from keyring.

    Silently does nothing if the key doesn't exist.
    """
    keyname = _PROVIDER_KEYS.get(provider)
    if keyname is None:
        return
    try:
        keyring.delete_password(_SERVICE, keyname)
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception:
        pass


def has_any_key() -> bool:
    """Return ``True`` if at least one API key is stored in keyring."""
    return any(get_api_key(p) for p in _PROVIDER_KEYS)
