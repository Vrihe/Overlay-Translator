"""
translate/google_client.py — Google Translate backend.

Hybrid mode:
  • If a Google Cloud API key is available → official Cloud Translation API v2.
  • If no key → free Web RPC endpoint (client=gtx), no auth required.

Public API
----------
translate(text, target_lang, source_lang) -> (detected_lang, translated_text)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

import settings
from translate.lang_codes import normalize_source_lang, normalize_target_lang

_logger = logging.getLogger("translator.google")

_TIMEOUT = 5  # seconds

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ── Official Cloud Translation API v2 ───────────────────


def _translate_official(
    text: str, target: str, source: str | None, api_key: str,
) -> tuple[str, str]:
    """Use the paid Cloud Translation API v2."""
    url = (
        f"https://translation.googleapis.com/language/translate/v2"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    body: dict = {"q": text, "target": target, "format": "text"}
    if source:
        body["source"] = source

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(
            f"Google Cloud Translation API вернул ошибку {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"Не удалось подключиться к Google Cloud Translation API: {exc}"
        ) from exc

    translations = result.get("data", {}).get("translations", [])
    if not translations:
        raise RuntimeError("Google Cloud Translation API вернул пустой ответ.")

    item = translations[0]
    detected = item.get("detectedSourceLanguage", source or "").lower()
    translated = item.get("translatedText", "")
    return detected, translated


# ── Free Web RPC (client=gtx) ───────────────────────────


def _translate_free(
    text: str, target: str, source: str | None,
) -> tuple[str, str]:
    """Use the public gtx endpoint — no API key required."""
    sl = source or "auto"
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": sl,
        "tl": target,
        "dt": "t",
        "q": text,
    })
    url = f"https://translate.googleapis.com/translate_a/single?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Google Translate (Web RPC) вернул ошибку {exc.code}."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"Не удалось подключиться к Google Translate: {exc}"
        ) from exc

    data = json.loads(raw)

    # data[0] is a list of [translated_segment, original_segment, ...] lists.
    segments = data[0] if isinstance(data[0], list) else []
    translated = "".join(
        seg[0] for seg in segments if isinstance(seg, list) and seg[0]
    )
    if not translated:
        raise RuntimeError("Google Translate вернул пустой ответ.")

    # data[2] holds the detected source language code (e.g. "en").
    detected = ""
    if len(data) > 2 and isinstance(data[2], str):
        detected = data[2].lower()

    return detected, translated


# ── Public API ───────────────────────────────────────────


def translate(
    text: str,
    target_lang: str = "ru",
    source_lang: str | None = None,
) -> tuple[str, str]:
    """Translate *text* via Google Translate.

    Returns ``(detected_source_lang, translated_text)``.
    """
    target = normalize_target_lang(target_lang, "google")
    source = normalize_source_lang(source_lang, "google")

    api_key = settings.get_api_key("google") or os.getenv("GOOGLE_API_KEY")

    if api_key:
        _logger.info("Google Cloud Translation API v2 (official key)")
        return _translate_official(text, target, source, api_key)

    _logger.info("Google Translate Web RPC (client=gtx, no key)")
    return _translate_free(text, target, source)
