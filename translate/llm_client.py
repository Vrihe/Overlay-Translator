"""
translate/llm_client.py — translation via Anthropic API (Claude Haiku).

Flow:
  1. Check the SQLite cache for a previous translation of the same text.
  2. If not cached, send a compact prompt to Claude Haiku.
  3. Cache and return the result.

The API key is read from the environment variable ``ANTHROPIC_API_KEY``.
"""

import os

import anthropic

import config
from cache.store import get_cached, save_to_cache

# ── Anthropic client (lazy, created once) ────────────────

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Return a reusable Anthropic client, creating it on first call."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set.  "
                "Export it as an environment variable before running."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ── Public API ───────────────────────────────────────────

def translate(
    text: str,
    target_lang: str | None = None,
    *,
    model: str = "claude-haiku-4-20250414",
) -> str:
    """Translate *text* into *target_lang* using Claude Haiku.

    Parameters
    ----------
    text : str
        Source text (typically OCR output).
    target_lang : str, optional
        Target language name or ISO code.  Defaults to ``config.TARGET_LANG``.
    model : str
        Anthropic model identifier.

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

    # 2. Call Anthropic API.
    client = _get_client()

    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system="You are a translator. Reply with ONLY the translation, nothing else.",
        messages=[
            {
                "role": "user",
                "content": f"Translate to {target_lang}:\n\n{text}",
            }
        ],
    )

    translation = message.content[0].text.strip()

    # 3. Cache the result.
    save_to_cache(text, translation)

    return translation
