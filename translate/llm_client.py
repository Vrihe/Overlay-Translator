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
    """Return a reusable LLM client, detecting which API key to use."""
    global _client, _provider
    if _client is not None:
        return _client, _provider

    or_key = os.environ.get("OPENROUTER_API_KEY")
    ant_key = os.environ.get("ANTHROPIC_API_KEY")

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
            "No API key found. Please set OPENROUTER_API_KEY or ANTHROPIC_API_KEY in .env."
        )
    return _client, _provider


# ── Public API ───────────────────────────────────────────

def translate(text: str, target_lang: str | None = None) -> str:
    """Translate *text* into *target_lang* using the active LLM provider.

    Parameters
    ----------
    text : str
        Source text (typically OCR output).
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

    if target_lang is None:
        target_lang = config.TARGET_LANG

    # 1. Cache lookup.
    cached = get_cached(text)
    if cached is not None:
        _logger.info("CACHE HIT | text=%r", text[:120])
        return cached

    _logger.info("CACHE MISS | text=%r | calling API…", text[:120])

    # 2. Call the chosen LLM API.
    t0 = time.perf_counter()
    client, provider = _get_client()
    system_prompt = "You are a translator. Reply with ONLY the translation, nothing else."
    user_prompt = f"Translate to {target_lang}:\n\n{text}"

    if provider == "openrouter":
        model = "google/gemma-4-26b-a4b-it:free"

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
        translation = response.choices[0].message.content.strip()
    else:
        model = "claude-haiku-4-20250414"
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        translation = message.content[0].text.strip()

    elapsed = time.perf_counter() - t0
    _logger.info(
        "API OK | provider=%s model=%s | %.2fs | src=%r | result=%r",
        provider, model, elapsed, text[:80], translation[:80],
    )

    # 3. Cache the result.
    save_to_cache(text, translation)

    return translation
