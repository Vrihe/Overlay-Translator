"""
translate/lang_codes.py — language-code normalization for NMT backends.

Each translation service expects its own flavour of language tags:
  • DeepL target codes are UPPER-CASE, some need a regional suffix (EN-US, PT-PT, ZH-HANS).
  • DeepL source codes are always two-letter upper-case (EN, RU, …).
  • Google / Azure use lower-case ISO 639-1 with a few exceptions (zh → zh-CN).

Functions
---------
normalize_target_lang(lang, backend)
    Convert a generic ISO 639-1 code to the target-language tag the backend expects.

normalize_source_lang(lang, backend)
    Convert a generic ISO 639-1 code (or "auto" / None) to the source-language tag,
    returning None when the backend should auto-detect.
"""

from __future__ import annotations

# ── DeepL target-language overrides ──────────────────────
# Keys: lower-cased input code → DeepL target tag.
# Any code NOT listed here is simply upper-cased (e.g. "de" → "DE").

_DEEPL_TARGET_MAP: dict[str, str] = {
    "en":    "EN-US",      # DeepL requires a variant for English targets
    "pt":    "PT-PT",      # European Portuguese by default
    "pt-br": "PT-BR",
    "zh":    "ZH-HANS",    # Simplified Chinese
    "zh-tw": "ZH-HANT",   # Traditional Chinese (Taiwan)
}

# ── Google / Azure target-language overrides ─────────────

_GOOGLE_AZURE_TARGET_MAP: dict[str, str] = {
    "zh": "zh-CN",         # Simplified Chinese
}


def normalize_target_lang(lang: str, backend: str) -> str:
    """Return the target-language tag expected by *backend*.

    Parameters
    ----------
    lang : str
        An ISO 639-1 code such as ``"en"``, ``"ru"``, ``"zh"``.
    backend : str
        One of ``"google"``, ``"deepl"``, ``"azure"``.
    """
    code = lang.strip().lower()

    if backend == "deepl":
        return _DEEPL_TARGET_MAP.get(code, code.upper())

    # google / azure
    return _GOOGLE_AZURE_TARGET_MAP.get(code, code)


def normalize_source_lang(lang: str | None, backend: str) -> str | None:
    """Return the source-language tag, or ``None`` for auto-detection.

    Parameters
    ----------
    lang : str | None
        An ISO 639-1 code, ``"auto"``, or ``None``.
    backend : str
        One of ``"google"``, ``"deepl"``, ``"azure"``.
    """
    if lang is None or lang.strip().lower() in ("auto", ""):
        return None

    code = lang.strip().lower()

    if backend == "deepl":
        # DeepL source codes are always two-letter upper-case (no regional suffix).
        return code[:2].upper()

    # google / azure — lower-case
    return code
