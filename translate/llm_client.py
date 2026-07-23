"""
translate/llm_client.py — translation via OpenRouter (free models) or Anthropic.

Flow:
  1. Check the SQLite cache for a previous translation.
  2. Detect API key. OpenRouter takes priority if OPENROUTER_API_KEY is set.
  3. Send a compact prompt to the LLM.
  4. Cache and return the result.

Every request is logged to the file specified by ``config.LOG_FILE``.
"""

import logging
import os
import time

import openai
import anthropic

import config
import settings
from cache.store import get_cached, save_to_cache

# ── File logger ──────────────────────────────────────────

_logger = logging.getLogger("translator")
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    _fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_fh)

# ── LLM client (lazy, created once) ─────────────────────

_client = None
_provider = None


def _get_client():
    """Return a reusable LLM client, detecting which API key to use.

    Key resolution priority (per provider):
      1. keyring  (set via UI dialogs)
      2. environment variable  (for dev workflow with .env)
    """
    global _client, _provider
    if _client is not None:
        return _client, _provider

    # Priority: keyring → env var.  OpenRouter checked before Anthropic.
    or_key = settings.get_api_key("openrouter") or os.environ.get("OPENROUTER_API_KEY")
    ant_key = settings.get_api_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY")

    if or_key:
        _client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
        )
        _provider = "openrouter"
        _logger.info("LLM provider: OpenRouter")
    elif ant_key:
        _client = anthropic.Anthropic(api_key=ant_key)
        _provider = "anthropic"
        _logger.info("LLM provider: Anthropic")
    else:
        raise RuntimeError(
            "No API key found.\n"
            "Set your key via the Settings dialog or place it in .env."
        )
    return _client, _provider


def reset_client() -> None:
    """Discard the cached LLM client so the next call picks up new keys."""
    global _client, _provider
    _client = None
    _provider = None
    _logger.info("LLM client reset — new key will be used on next request.")


# ── Public API ───────────────────────────────────────────

def translate(text: str, *, source_lang: str | None = None,
             target_lang: str | None = None) -> str:
    """Translate *text* into *target_lang* using the active LLM provider.

    Parameters
    ----------
    text : str
        Source text (typically OCR output).
    source_lang : str, optional
        ISO 639-1 source language code (e.g. ``'en'``).  Used for the
        cache key and for the LLM prompt.  Defaults to
        ``config.SOURCE_LANG``.
    target_lang : str, optional
        Target language name or ISO code. Defaults to ``config.TARGET_LANG``.

    Returns
    -------
    str
        Translated text.
    """
    text = text.strip()
    if not text:
        return ""

    if source_lang is None:
        source_lang = config.SOURCE_LANG
    if target_lang is None:
        target_lang = config.TARGET_LANG

    # 1. Cache lookup.
    cached = get_cached(text, source_lang, target_lang)
    if cached is not None:
        _logger.info("CACHE HIT | text=%r", text[:120])
        return cached

    _logger.info("CACHE MISS | text=%r | calling API…", text[:120])

    # 2. Call the chosen LLM API.
    t0 = time.perf_counter()
    client, provider = _get_client()
    system_prompt = "You are a translator. Reply with ONLY the translation, nothing else."
    user_prompt = f"Translate from {source_lang} to {target_lang}:\n\n{text}"

    if provider == "openrouter":
        model = config.LLM_MODEL

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            extra_headers={
                "HTTP-Referer": "https://github.com/your-username/overlay-translator",
                "X-Title": "Overlay Translator"
            }
        )
        if not response or not getattr(response, "choices", None):
            raise RuntimeError(f"OpenRouter API не вернул варианты ответа ({response=}). Проверьте ключ или модель.")
        
        choice = response.choices[0]
        if not hasattr(choice, "message") or choice.message is None or choice.message.content is None:
            raise RuntimeError("OpenRouter API вернул пустой текст ответа.")

        translation = choice.message.content.strip()
    else:
        model = config.LLM_MODEL
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        if not message or not getattr(message, "content", None):
            raise RuntimeError("Anthropic API не вернул текст ответа.")
        translation = message.content[0].text.strip()

    elapsed = time.perf_counter() - t0
    _logger.info(
        "API OK | provider=%s model=%s | %.2fs | src=%r | result=%r",
        provider, model, elapsed, text[:80], translation[:80],
    )

    # 3. Cache the result.
    save_to_cache(text, source_lang, target_lang, translation)

    return translation


# ── Combined detect + translate (single LLM call) ───────

def detect_and_translate(text: str, *,
                         target_lang: str | None = None) -> tuple[str, str]:
    """Detect the source language *and* translate in a single LLM call.

    This is used when ``LANG_DETECT_ENGINE == "llm"`` to avoid two
    separate API round-trips.  The LLM is asked to reply in the strict
    format ``LANG: <code>\n<translation>`` so we can parse both the
    detected ISO 639-1 code and the translated text from one response.

    Parameters
    ----------
    text : str
        Source text (typically OCR output — may contain noise, slang,
        mixed scripts from game chat).
    target_lang : str, optional
        Target language ISO code.  Defaults to ``config.TARGET_LANG``.

    Returns
    -------
    tuple[str, str]
        ``(detected_source_lang, translated_text)``.
    """
    text = text.strip()
    if not text:
        return config.SOURCE_LANG, ""

    if target_lang is None:
        target_lang = config.TARGET_LANG

    # Cache lookup uses SOURCE_LANG as a sentinel — we don't know the
    # real source lang yet, so we use a special key prefix.
    cached = get_cached(text, "_auto", target_lang)
    if cached is not None:
        _logger.info("CACHE HIT (auto) | text=%r", text[:120])
        # We don't know the original detected lang from cache, but the
        # translation is valid.  Return SOURCE_LANG as a best guess.
        return config.SOURCE_LANG, cached

    _logger.info("CACHE MISS (auto) | text=%r | calling API…", text[:120])

    t0 = time.perf_counter()
    client, provider = _get_client()

    system_prompt = (
        "You are a translator.  The input text may be noisy OCR output "
        "from a game screen (slang, typos, mixed scripts, garbled characters).  "
        "First, determine the source language of the text.  "
        "Then translate it into the target language.  "
        "Reply in EXACTLY this format (two lines, nothing else):\n"
        "LANG: <ISO 639-1 two-letter code>\n"
        "<translated text>"
    )
    user_prompt = f"Translate to {target_lang}:\n\n{text}"

    if provider == "openrouter":
        model = config.OPENROUTER_MODEL
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            extra_headers={
                "HTTP-Referer": "https://github.com/your-username/overlay-translator",
                "X-Title": "Overlay Translator",
            },
        )
        if not response or not getattr(response, "choices", None):
            raise RuntimeError(
                f"OpenRouter API не вернул варианты ответа ({response=})."
            )
        choice = response.choices[0]
        if not hasattr(choice, "message") or choice.message is None or choice.message.content is None:
            raise RuntimeError("OpenRouter API вернул пустой текст ответа.")
        raw = choice.message.content.strip()
    else:
        model = "claude-haiku-4-20250414"
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not message or not getattr(message, "content", None):
            raise RuntimeError("Anthropic API не вернул текст ответа.")
        raw = message.content[0].text.strip()

    elapsed = time.perf_counter() - t0

    # Parse "LANG: xx\n<translation>"
    detected_lang = config.SOURCE_LANG
    translation = raw
    lines = raw.split("\n", 1)
    if len(lines) >= 2 and lines[0].upper().startswith("LANG:"):
        code = lines[0].split(":", 1)[1].strip().lower()[:2]
        if len(code) == 2 and code.isalpha():
            detected_lang = code
        translation = lines[1].strip()

    _logger.info(
        "API OK (auto) | provider=%s model=%s | %.2fs | lang=%s | src=%r | result=%r",
        provider, model, elapsed, detected_lang, text[:80], translation[:80],
    )

    # Cache with the special "_auto" source key.
    save_to_cache(text, "_auto", target_lang, translation)

    return detected_lang, translation
