"""
translate/llm_client.py — translation via OpenRouter (free models) or Anthropic with retry & fallback.

Flow:
  1. Check the SQLite cache for a previous translation.
  2. Determine provider chain (Primary -> Fallback).
  3. Send prompt using resilience orchestrator (_call_with_resilience).
  4. Cache and return the result.

Every request is logged to the file specified by ``config.LOG_FILE``.
"""

import logging
import os
import threading
import time

# openai and anthropic are imported lazily inside _get_client_for()
# to avoid ~200-500ms startup cost before the first translation request.

import config
import settings
from cache.store import get_cached, save_to_cache
from translate.domain_manager import load_domain_profile
from translate.error_classification import is_retryable

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

# ── LLM clients & resilience ────────────────────────────

_clients_cache: dict[str, object] = {}
_client = None
_provider = None

# ── System prompt cache (A1) ─────────────────────────────
# Keyed by "domain_id:target_lang:source_lang" — cleared on reset_client().
_prompt_cache: dict[str, str] = {}

# ── Request coalescing (1.2) ──────────────────────────
# When two threads request the same (text, src, tgt, domain) simultaneously,
# the second one waits for the first and reuses its result without an extra API call.

class _InflightRequest:
    """Shared state between an in-flight owner thread and any waiting threads."""
    __slots__ = ("event", "result")

    def __init__(self):
        self.event: threading.Event = threading.Event()
        self.result: str | Exception | None = None


_in_flight: dict[tuple, _InflightRequest] = {}
_in_flight_lock = threading.Lock()


def _get_client_for(provider_name: str):
    """Return a client instance for *provider_name* or None if API key is not set."""
    if provider_name in _clients_cache:
        return _clients_cache[provider_name]

    if provider_name == "openrouter":
        key = settings.get_api_key("openrouter") or os.getenv("OPENROUTER_API_KEY")
        if not key:
            return None
        import openai  # lazy: loaded on first translation request
        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
        )
        _clients_cache["openrouter"] = client
        return client

    if provider_name == "anthropic":
        key = settings.get_api_key("anthropic") or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            return None
        import anthropic  # lazy: loaded on first translation request
        client = anthropic.Anthropic(api_key=key)
        _clients_cache["anthropic"] = client
        return client

    return None


def get_provider_chain() -> list[str]:
    """Return an ordered list of configured providers (primary first, fallback second)."""
    primary = settings.get_primary_provider() if hasattr(settings, "get_primary_provider") else "openrouter"
    all_providers = ["openrouter", "anthropic"]
    if primary in all_providers:
        chain = [primary] + [p for p in all_providers if p != primary]
    else:
        chain = all_providers

    if hasattr(settings, "is_fallback_enabled") and not settings.is_fallback_enabled():
        chain = chain[:1]

    return [p for p in chain if _get_client_for(p) is not None]


def _get_client():
    """Return a tuple of ``(client, provider_name)`` for the primary provider in chain."""
    global _client, _provider
    chain = get_provider_chain()
    if not chain:
        raise RuntimeError(
            "API key missing! Please set OpenRouter or Anthropic API key in Settings or environment variables."
        )
    _provider = chain[0]
    _client = _get_client_for(_provider)
    return _client, _provider


def reset_client() -> None:
    """Force re-creation of LLM clients on next request."""
    global _clients_cache, _client, _provider
    _client = None
    _provider = None
    _clients_cache.clear()
    _prompt_cache.clear()  # A1: invalidate cached system prompts on settings change
    _logger.info("LLM clients cache reset — new keys/models will be used on next request.")


def _dynamic_max_tokens(text: str) -> int:
    """A4: Estimate a reasonable max_tokens ceiling based on input length.

    Translation output is rarely longer than the input × 2.
    Clamp to [64, 1024] to avoid both truncation and over-reservation.
    """
    word_count = len(text.split())
    return max(64, min(1024, word_count * 4))


def _call_provider(
    client,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    on_chunk=None,  # A5: optional callable(partial_text: str) for streaming
) -> str:
    """Execute a single LLM API call for *provider*. Raise exception on error.

    If *on_chunk* is provided the response is streamed and *on_chunk* is called
    with the accumulated partial translation after every received token.
    Streaming is supported for OpenRouter (OpenAI-compatible) and Anthropic.
    """
    if provider == "openrouter":
        if on_chunk is not None:
            # A5: streaming path
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                extra_headers={
                    "HTTP-Referer": "https://github.com/your-username/overlay-translator",
                    "X-Title": "Overlay Translator",
                },
                stream=True,
            )
            chunks: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    chunks.append(delta)
                    on_chunk("".join(chunks))
            result = "".join(chunks).strip()
            if not result:
                raise RuntimeError("OpenRouter API (stream) вернул пустой текст ответа.")
            return result
        else:
            # non-streaming path (fallback / retry uses this)
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
                raise RuntimeError(f"OpenRouter API не вернул варианты ответа ({response=}).")
            choice = response.choices[0]
            if not hasattr(choice, "message") or choice.message is None or choice.message.content is None:
                raise RuntimeError("OpenRouter API вернул пустой текст ответа.")
            return choice.message.content.strip()

    if provider == "anthropic":
        # A4: use dynamic ceiling instead of hard-coded 2048
        max_tok = _dynamic_max_tokens(user_prompt)
        if on_chunk is not None:
            # A5: Anthropic streaming via context manager
            chunks: list[str] = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tok,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    on_chunk("".join(chunks))
            result = "".join(chunks).strip()
            if not result:
                raise RuntimeError("Anthropic API (stream) вернул пустой текст ответа.")
            return result
        else:
            message = client.messages.create(
                model=model,
                max_tokens=max_tok,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if not message or not getattr(message, "content", None):
                raise RuntimeError("Anthropic API не вернул текст ответа.")
            return message.content[0].text.strip()

    raise ValueError(f"Unknown provider: {provider!r}")


def _call_with_resilience(
    system_prompt: str,
    user_prompt: str,
    model_for: dict[str, str],
    on_chunk=None,  # A5: forwarded to _call_provider for streaming; None = non-streaming
) -> tuple[str, str]:
    """Execute request across available provider chain with retry on transient errors.

    model_for: mapping of provider_name -> model_name
    on_chunk:  optional callable(partial_text: str) — enables streaming on first try only;
               retries and fallback providers always use non-streaming to avoid double-emit.
    Returns: (raw_text, provider_used)
    Raises RuntimeError if all providers in chain fail.
    """
    chain = get_provider_chain()
    if not chain:
        raise RuntimeError(
            "Нет доступных провайдеров — проверьте, что задан хотя бы один API-ключ "
            "(Anthropic или OpenRouter) в Настройках."
        )

    errors: dict[str, Exception] = {}
    max_retries = getattr(config, "MAX_RETRIES_PER_PROVIDER", 2)
    backoff_base = getattr(config, "RETRY_BACKOFF_BASE_SEC", 1.0)

    for provider_idx, provider_name in enumerate(chain):
        client = _get_client_for(provider_name)
        model = model_for.get(provider_name, config.LLM_MODEL)

        for attempt in range(max_retries + 1):
            # A5: stream only on the very first attempt of the primary provider;
            # retries and fallback providers use non-streaming to avoid partial emit issues.
            chunk_cb = on_chunk if (provider_idx == 0 and attempt == 0) else None
            try:
                result = _call_provider(client, provider_name, model, system_prompt, user_prompt, on_chunk=chunk_cb)
                if attempt > 0 or provider_name != chain[0]:
                    _logger.warning(
                        "RESILIENCE | succeeded via provider=%s after %d attempt(s), chain=%s",
                        provider_name, attempt + 1, chain,
                    )
                return result, provider_name
            except Exception as e:
                errors[f"{provider_name}#attempt_{attempt}"] = e
                if is_retryable(e) and attempt < max_retries:
                    wait = backoff_base * (2 ** attempt)
                    _logger.warning(
                        "RESILIENCE | provider=%s attempt=%d failed (%s: %s), retrying in %.1fs",
                        provider_name, attempt, type(e).__name__, e, wait,
                    )
                    time.sleep(wait)
                    continue
                _logger.warning(
                    "RESILIENCE | provider=%s exhausted/non-retryable (%s: %s), moving to next in chain",
                    provider_name, type(e).__name__, e,
                )
                break

    summary = "; ".join(f"{k}: {type(v).__name__}: {v}" for k, v in errors.items())
    raise RuntimeError(f"Все провайдеры недоступны. Детали: {summary}")


def _build_system_prompt(domain_id: str, target_lang: str, source_lang: str | None = None) -> str:
    """Build domain-aware system prompt including few-shot examples.

    A1: Result is cached in _prompt_cache keyed by (domain_id, target_lang, source_lang)
    so repeated calls with the same arguments skip JSON file I/O and string concatenation.
    Cache is invalidated by reset_client() whenever settings change.
    """
    cache_key = f"{domain_id}:{target_lang}:{source_lang}"
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]

    profile = load_domain_profile(domain_id)
    base_sys_prompt = profile.get("system_prompt", "Ты профессиональный переводчик.")
    few_shots = profile.get("few_shot_examples", [])

    parts = [base_sys_prompt]
    if source_lang and source_lang != "auto":
        parts.append(f"Translate from {source_lang} to {target_lang}.")
    else:
        parts.append(f"Translate to {target_lang}.")

    if few_shots:
        parts.append("\nExamples:")
        for ex in few_shots:
            s_ex = ex.get("source", "").strip()
            t_ex = ex.get("translation", "").strip()
            if s_ex and t_ex:
                parts.append(f"  {s_ex!r} → {t_ex!r}")

    parts.append("Output ONLY the translation. No explanations, no quotes, no preamble.")
    result = "\n".join(parts)
    _prompt_cache[cache_key] = result
    return result


# ── Public API ───────────────────────────────────────────

def translate(
    text: str,
    target_lang: str | None = None,
    source_lang: str | None = None,
    domain_id: str | None = None,
    on_chunk=None,  # A5: optional callable(partial_text: str) — enables streaming UI updates
) -> str:
    """Translate *text* into *target_lang* using active domain profile & LLM provider.

    Parameters
    ----------
    on_chunk : callable(str) | None
        If provided, called incrementally with the accumulated partial translation
        as tokens stream in. Enables live UI updates without waiting for full response.
        When *on_chunk* is None the call is non-streaming (default).
    """
    text = text.strip()
    if not text:
        return ""

    if source_lang is None:
        source_lang = config.SOURCE_LANG
    if target_lang is None:
        target_lang = config.TARGET_LANG
    if domain_id is None:
        domain_id = getattr(config, "ACTIVE_DOMAIN", "general")

    # 1. Cache lookup — streaming skipped on cache hit (result is instant).
    cached = get_cached(text, source_lang, target_lang, domain_id=domain_id)
    if cached is not None:
        _logger.info("CACHE HIT | domain=%s | text=%r", domain_id, text[:120])
        return cached

    _logger.info("CACHE MISS | domain=%s | text=%r | calling API…", domain_id, text[:120])

    # 2. Request coalescing — deduplicate concurrent requests for the same text.
    coal_key = (text, source_lang, target_lang, domain_id)
    with _in_flight_lock:
        if coal_key in _in_flight:
            req = _in_flight[coal_key]
            is_owner = False
        else:
            req = _InflightRequest()
            _in_flight[coal_key] = req
            is_owner = True

    if not is_owner:
        # Another thread is already translating this exact text — wait and reuse.
        _logger.info("COALESCE | waiting for in-flight request | text=%r", text[:80])
        req.event.wait(timeout=120.0)  # generous timeout; owner raises on failure
        if isinstance(req.result, Exception):
            raise req.result
        return req.result or ""

    # 3. Call LLM API via resilience orchestrator (we are the owner).
    try:
        t0 = time.perf_counter()
        system_prompt = _build_system_prompt(domain_id, target_lang, source_lang)
        # A3: user_prompt contains only the source text — language direction is already
        # embedded in system_prompt, so repeating it here wastes input tokens.
        user_prompt = text
        model_for = {
            "openrouter": config.LLM_MODEL,
            "anthropic": config.LLM_MODEL,
        }

        translation, provider = _call_with_resilience(system_prompt, user_prompt, model_for, on_chunk=on_chunk)
        model = model_for.get(provider, config.LLM_MODEL)

        elapsed = time.perf_counter() - t0
        _logger.info(
            "API OK | provider=%s domain=%s model=%s | %.2fs | src=%r | result=%r",
            provider, domain_id, model, elapsed, text[:80], translation[:80],
        )

        # 4. Cache the result with domain_id.
        save_to_cache(text, source_lang, target_lang, translation, domain_id=domain_id)

        req.result = translation
        return translation

    except Exception as exc:
        req.result = exc
        raise

    finally:
        # Release waiting threads and remove from in-flight registry.
        req.event.set()
        with _in_flight_lock:
            _in_flight.pop(coal_key, None)


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

    profile = load_domain_profile(domain_id)
    base_sys_prompt = profile.get("system_prompt", "")
    few_shots = profile.get("few_shot_examples", [])

    sys_parts = [
        "You are an expert translator and OCR text restorer.",
        "The input text is extracted via screen OCR and may contain garbled characters, typos (e.g., 'malnpy' -> 'main.py'), or mixed scripts.",
        "Your task:",
        "1. Determine the source language of the text.",
        "2. Fix any OCR typos/garbled characters in the input.",
        f"3. Translate the restored text into {target_lang}.",
        "4. If the input contains code filenames, technical terms, or English words, translate them into Russian while fixing OCR errors.",
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

    model_for = {
        "openrouter": getattr(config, "OPENROUTER_MODEL", config.LLM_MODEL),
        "anthropic": getattr(config, "ANTHROPIC_DETECT_MODEL", "claude-haiku-4-20250414"),
    }

    raw, provider = _call_with_resilience(system_prompt, user_prompt, model_for)
    model = model_for.get(provider, config.LLM_MODEL)

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
