"""
translate/llm_client.py — translation via OpenRouter (free models) or Anthropic.

Flow:
  1. Check the SQLite cache for a previous translation.
  2. Detect API key. OpenRouter takes priority if OPENROUTER_API_KEY is set.
  3. Send a compact prompt to the LLM.
  4. Cache and return the result.
"""

import os
import openai
import anthropic

import config
from cache.store import get_cached, save_to_cache

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
    elif ant_key:
        _client = anthropic.Anthropic(api_key=ant_key)
        _provider = "anthropic"
    else:
        raise RuntimeError(
            "No API key found. Please set OPENROUTER_API_KEY or ANTHROPIC_API_KEY in .env."
        )
    return _client, _provider


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
        return cached

    # 2. Call the chosen LLM API.
    client, provider = _get_client()
    system_prompt = "You are a translator. Reply with ONLY the translation, nothing else."
    user_prompt = f"Translate to {target_lang}:\n\n{text}"

    if provider == "openrouter":
        # Example free model on OpenRouter:
        # Others include: mistralai/mistral-7b-instruct:free, meta-llama/llama-3-8b-instruct:free
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
        # Anthropic direct API fallback
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

    # 3. Cache the result.
    save_to_cache(text, translation)

    return translation
