"""
translate/deepl_client.py — DeepL API backend.

Supports both Free and Pro tiers: the endpoint is chosen automatically
based on the API key suffix (`:fx` → api-free.deepl.com).

An API key is **required**; without one the function raises RuntimeError
with a user-friendly message.

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

_logger = logging.getLogger("translator.deepl")

_TIMEOUT = 5  # seconds


def translate(
    text: str,
    target_lang: str = "ru",
    source_lang: str | None = None,
) -> tuple[str, str]:
    """Translate *text* via the DeepL API.

    Returns ``(detected_source_lang, translated_text)``.

    Raises ``RuntimeError`` when the API key is missing or the request fails.
    """
    # ── Resolve key ──────────────────────────────────────
    api_key = settings.get_api_key("deepl") or os.getenv("DEEPL_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DeepL API key missing! Укажите ключ в Настройках."
        )

    # ── Endpoint selection ───────────────────────────────
    if api_key.rstrip().endswith(":fx"):
        base = "https://api-free.deepl.com"
    else:
        base = "https://api.deepl.com"
    url = f"{base}/v2/translate"

    # ── Build request body ───────────────────────────────
    target = normalize_target_lang(target_lang, "deepl")
    source = normalize_source_lang(source_lang, "deepl")

    body: dict = {"text": [text], "target_lang": target}
    if source:
        body["source_lang"] = source

    _logger.info(
        "DeepL %s → target=%s source=%s",
        "Free" if ":fx" in api_key else "Pro", target, source or "auto",
    )

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"DeepL-Auth-Key {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    # ── Execute ──────────────────────────────────────────
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code == 403:
            raise RuntimeError(
                "DeepL: ключ недействителен или заблокирован (403 Forbidden)."
            ) from exc
        if exc.code == 456:
            raise RuntimeError(
                "DeepL: превышена квота символов. Проверьте лимит вашего тарифа."
            ) from exc
        raise RuntimeError(
            f"DeepL API вернул ошибку {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"Не удалось подключиться к DeepL API: {exc}"
        ) from exc

    translations = result.get("translations", [])
    if not translations:
        raise RuntimeError("DeepL API вернул пустой ответ.")

    item = translations[0]
    detected = item.get("detected_source_language", "").lower()
    translated = item.get("text", "")
    return detected, translated
