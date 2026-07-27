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
from translate.domain_manager import load_domain_profile

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
    """Return a tuple of ``(client, provider_name)``."""
    global _client, _provider

    if _client is not None:
        return _client, _provider

    openrouter_key = settings.get_api_key("openrouter") or os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        _client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
        )
        _provider = "openrouter"
        _logger.info("Initialized OpenRouter client (model: %s)", config.LLM_MODEL)
        return _client, _provider

    anthropic_key = settings.get_api_key("anthropic") or os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        _client = anthropic.Anthropic(api_key=anthropic_key)
        _provider = "anthropic"
        _logger.info("Initialized Anthropic client (model: %s)", config.LLM_MODEL)
        return _client, _provider

    raise RuntimeError(
        "API key missing! Please set OpenRouter or Anthropic API key in Settings or environment variables."
    )


def reset_client() -> None:
    """Force re-creation of the LLM client on next request."""
    global _client, _provider
    _client = None
    _provider = None
    _logger.info("LLM client reset — new key will be used on next request.")


def _build_system_prompt(domain_id: str, target_lang: str, source_lang: str | None = None) -> str:
    """Build domain-aware system prompt including few-shot examples."""
    profile = load_domain_profile(domain_id)
    base_sys_prompt = profile.get("system_prompt", "Ты профессиональный переводчик.")
    few_shots = profile.get("few_shot_examples", [])

    parts = [base_sys_prompt]
    if source_lang and source_lang != "auto":
        parts.append(f"Переводи с {source_lang} на {target_lang}.")
    else:
        parts.append(f"Переводи на {target_lang}.")

    if few_shots:
        parts.append("\nПримеры перевода (Few-Shot Examples):")
        for ex in few_shots:
            s_ex = ex.get("source", "").strip()
            t_ex = ex.get("translation", "").strip()
            if s_ex and t_ex:
                parts.append(f"• \"{s_ex}\" → \"{t_ex}\"")

    parts.append("Отвечай ИСКЛЮЧИТЕЛЬНО готовым переводом, без вводных фраз, пояснений и без кавычек.")
    return "\n".join(parts)


# ── Public API ───────────────────────────────────────────

def translate(
    text: str,
    target_lang: str | None = None,
    source_lang: str | None = None,
    domain_id: str | None = None,
) -> str:
    """Translate *text* into *target_lang* using active domain profile & LLM provider."""
    text = text.strip()
    if not text:
        return ""

    if source_lang is None:
        source_lang = config.SOURCE_LANG
    if target_lang is None:
        target_lang = config.TARGET_LANG
    if domain_id is None:
        domain_id = getattr(config, "ACTIVE_DOMAIN", "general")

    # 1. Cache lookup with domain_id.
    cached = get_cached(text, source_lang, target_lang, domain_id=domain_id)
    if cached is not None:
        _logger.info("CACHE HIT | domain=%s | text=%r", domain_id, text[:120])
        return cached

    _logger.info("CACHE MISS | domain=%s | text=%r | calling API…", domain_id, text[:120])

    # 2. Call the chosen LLM API.
    t0 = time.perf_counter()
    client, provider = _get_client()
    system_prompt = _build_system_prompt(domain_id, target_lang, source_lang)
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
        "API OK | provider=%s domain=%s model=%s | %.2fs | src=%r | result=%r",
        provider, domain_id, model, elapsed, text[:80], translation[:80],
    )

    # 3. Cache the result with domain_id.
    save_to_cache(text, source_lang, target_lang, translation, domain_id=domain_id)

    return translation


# ── Combined detect + translate (single LLM call) ───────

def detect_and_translate(
    text: str,
    target_lang: str | None = None,
    domain_id: str | None = None,
) -> tuple[str, str]:
    """Detect the source language *and* translate in a single LLM call with domain profile."""
    text = text.strip()
    if not text:
        return config.SOURCE_LANG, ""

    if target_lang is None:
        target_lang = config.TARGET_LANG
    if domain_id is None:
        domain_id = getattr(config, "ACTIVE_DOMAIN", "general")

    cached = get_cached(text, "_auto", target_lang, domain_id=domain_id)
    if cached is not None:
        _logger.info("CACHE HIT (auto) | domain=%s | text=%r", domain_id, text[:120])
        return config.SOURCE_LANG, cached

    _logger.info("CACHE MISS (auto) | domain=%s | text=%r | calling API…", domain_id, text[:120])

    t0 = time.perf_counter()
    client, provider = _get_client()

    profile = load_domain_profile(domain_id)
    base_sys_prompt = profile.get("system_prompt", "")
    few_shots = profile.get("few_shot_examples", [])

    sys_parts = [
        "You are a translator.",
        "The input text may be noisy OCR output from a screen (slang, typos, mixed scripts, garbled characters).",
        "First, determine the source language of the text.",
        "Then translate it into the target language.",
    ]
    if base_sys_prompt:
        sys_parts.append(f"Domain Guidelines: {base_sys_prompt}")

    if few_shots:
        sys_parts.append("Translation Examples:")
        for ex in few_shots:
            s_ex = ex.get("source", "").strip()
            t_ex = ex.get("translation", "").strip()
            if s_ex and t_ex:
                sys_parts.append(f"• \"{s_ex}\" → \"{t_ex}\"")

    sys_parts.append(
        "Reply in EXACTLY this format (two lines, nothing else):\n"
        "LANG: <ISO 639-1 two-letter code>\n"
        "<translated text>"
    )
    system_prompt = "\n".join(sys_parts)
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
        "API OK (auto) | provider=%s domain=%s model=%s | %.2fs | lang=%s | src=%r | result=%r",
        provider, domain_id, model, elapsed, detected_lang, text[:80], translation[:80],
    )

    # Cache with the special "_auto" source key.
    save_to_cache(text, "_auto", target_lang, translation, domain_id=domain_id)

    return detected_lang, translation
