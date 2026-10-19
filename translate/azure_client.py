"""
translate/azure_client.py — Microsoft Azure Translator backend (REST API v3.0).

Requires an Azure Cognitive Services Translator key and, optionally, a region
(defaults to ``"global"``).

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
from settings import config_manager
from translate.lang_codes import normalize_source_lang, normalize_target_lang

_logger = logging.getLogger("translator.azure")

_TIMEOUT = 5  # seconds

_BASE_URL = "https://api.cognitive.microsofttranslator.com/translate"


def translate(
    text: str,
    target_lang: str = "ru",
    source_lang: str | None = None,
) -> tuple[str, str]:
    """Translate *text* via the Azure Translator REST API v3.0.

    Returns ``(detected_source_lang, translated_text)``.

    Raises ``RuntimeError`` when the API key is missing or the request fails.
    """
    # ── Resolve credentials ──────────────────────────────
    api_key = settings.get_api_key("azure") or os.getenv("AZURE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Azure Translator API key missing! Укажите ключ в Настройках."
        )
    region = config_manager.get("azure_region") or "global"

    # ── Build URL ────────────────────────────────────────
    target = normalize_target_lang(target_lang, "azure")
    source = normalize_source_lang(source_lang, "azure")

    params: dict[str, str] = {"api-version": "3.0", "to": target}
    if source:
        params["from"] = source
    url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"

    _logger.info("Azure Translator → target=%s source=%s region=%s",
                 target, source or "auto", region)

    # ── Build request ────────────────────────────────────
    body = json.dumps([{"Text": text}]).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Ocp-Apim-Subscription-Key": api_key,
            "Ocp-Apim-Subscription-Region": region,
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
        if exc.code == 401:
            raise RuntimeError(
                "Azure Translator: ключ недействителен или регион указан неверно (401)."
            ) from exc
        if exc.code == 403:
            raise RuntimeError(
                "Azure Translator: доступ запрещён (403). Проверьте подписку."
            ) from exc
        raise RuntimeError(
            f"Azure Translator API вернул ошибку {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"Не удалось подключиться к Azure Translator API: {exc}"
        ) from exc

    if not result or not isinstance(result, list):
        raise RuntimeError("Azure Translator API вернул пустой ответ.")

    entry = result[0]
    translations = entry.get("translations", [])
    if not translations:
        raise RuntimeError("Azure Translator API вернул пустой ответ.")

    translated = translations[0].get("text", "")

    # `detectedLanguage` is present only when `from` was not specified.
    detected_obj = entry.get("detectedLanguage", {})
    detected = detected_obj.get("language", source or "").lower()

    return detected, translated
