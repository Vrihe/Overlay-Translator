"""
translate/backend.py — chooses between the API and the local NLLB translator.

Exposes exactly the surface ``translate.llm_client`` does, so call sites only
swap the import:

    translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None) -> str
    detect_and_translate(text, target_lang=None, domain_id=None, on_chunk=None) -> (lang, text)

Which backend runs is read from ``config.TRANSLATION_BACKEND`` on every call, so
a settings change takes effect immediately without restarting the app.

Supported backends:
  • "api"    — cloud LLM (OpenRouter / Anthropic) via translate.llm_client
  • "google" — Google Translate (Cloud API v2 or free Web RPC)
  • "deepl"  — DeepL API (Free / Pro)
  • "azure"  — Microsoft Azure Translator REST API v3.0
  • "nllb"   — local CTranslate2 NLLB-200 model

Error policy for the local backend (agreed with the user):
  • Model missing / fails to load  → fall back to the API backend and leave a
    notice for the UI (``take_notice()``), so the user learns why the request
    went online.
  • Model loaded, translation fails → the error propagates; no silent fallback.

The API path is untouched: when the active backend is ``"api"`` this module is a
thin pass-through to ``translate.llm_client``.
"""

from __future__ import annotations

import logging
import threading

import config

BACKEND_API = "api"
BACKEND_GOOGLE = "google"
BACKEND_DEEPL = "deepl"
BACKEND_AZURE = "azure"
BACKEND_NLLB = "nllb"

#: Set of all valid backend identifiers.
_VALID_BACKENDS = {BACKEND_API, BACKEND_GOOGLE, BACKEND_DEEPL, BACKEND_AZURE, BACKEND_NLLB}

#: Set of NMT (fast, non-LLM) backends handled via simple HTTP clients.
_NMT_BACKENDS = {BACKEND_GOOGLE, BACKEND_DEEPL, BACKEND_AZURE}

#: (id, human label) — consumed by ui/settings_dialog.
BACKENDS: list[tuple[str, str]] = [
    (BACKEND_API,    "LLM (OpenRouter / Anthropic)"),
    (BACKEND_GOOGLE, "Google Translate"),
    (BACKEND_DEEPL,  "DeepL API"),
    (BACKEND_AZURE,  "Microsoft Azure Translator"),
    (BACKEND_NLLB,   "Локальная модель (NLLB-200)"),
]

_logger = logging.getLogger("translator.backend")

# Per-thread one-shot notice, consumed by the UI right after a translation call.
# Thread-local because translations run on QThread workers and two of them must
# never read each other's notice.
_state = threading.local()


# ── Notices ──────────────────────────────────────────────


def _set_notice(message: str) -> None:
    _state.notice = message


def take_notice() -> str:
    """Return and clear the notice left by the last call on this thread."""
    notice = getattr(_state, "notice", "")
    _state.notice = ""
    return notice


def clear_notice() -> None:
    _state.notice = ""


# ── Backend selection ────────────────────────────────────


def get_active_backend() -> str:
    """Return the configured backend id, defaulting to the API on bad input."""
    value = (getattr(config, "TRANSLATION_BACKEND", BACKEND_API) or BACKEND_API)
    value = str(value).strip().lower()
    return value if value in _VALID_BACKENDS else BACKEND_API


def _api_fallback_notice(exc: Exception) -> str:
    first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return f"Локальная модель NLLB недоступна ({first_line}) — переведено через API."


def _nllb_ready() -> bool:
    """Try to load the local model; on failure record a notice and return False."""
    from translate.nllb_backend import NllbModelUnavailable, get_backend

    try:
        instance = get_backend()
        instance.ensure_loaded()
        # One-shot, e.g. "CUDA unavailable, using CPU inference" after the first load.
        notice = instance.take_notice()
        if notice:
            _set_notice(notice)
        return True
    except NllbModelUnavailable as exc:
        _logger.warning("NLLB unavailable, falling back to API: %s", exc)
        _set_notice(_api_fallback_notice(exc))
        return False


# ── NMT helper ───────────────────────────────────────────


def _get_nmt_client(backend: str):
    """Lazy-import and return the NMT client module for *backend*."""
    if backend == BACKEND_GOOGLE:
        from translate import google_client
        return google_client
    if backend == BACKEND_DEEPL:
        from translate import deepl_client
        return deepl_client
    if backend == BACKEND_AZURE:
        from translate import azure_client
        return azure_client
    raise ValueError(f"Unknown NMT backend: {backend!r}")


def _nmt_translate(
    backend: str,
    text: str,
    target_lang: str | None,
    source_lang: str | None,
    domain_id: str | None,
    on_chunk,
) -> tuple[str, str]:
    """Call the NMT client and return ``(detected_source_lang, translated_text)``.

    Checks the SQLite/LRU cache first — a hit returns in ~0 ms without a
    network round-trip.  On a miss the result is saved to cache for next time.
    """
    tgt = target_lang or config.TARGET_LANG or "ru"
    cache_domain = f"{domain_id}|{backend}" if domain_id else backend
    cache_src = source_lang or "_auto"

    # ── Cache lookup (L1 in-memory ~0 ms, L2 SQLite ~1-5 ms) ─
    try:
        from cache.store import get_cached
        cached = get_cached(text, cache_src, tgt, domain_id=cache_domain)
        if cached:
            _logger.debug("NMT cache hit (%s): %d chars", backend, len(cached))
            if on_chunk:
                on_chunk(cached)
            return cache_src, cached
    except Exception:
        pass  # cache miss or error — proceed to API

    # ── API call ─────────────────────────────────────────
    client = _get_nmt_client(backend)
    detected, translated = client.translate(text, target_lang=tgt, source_lang=source_lang)

    # Emulate streaming for the UI (NMT returns the whole result at once).
    if on_chunk:
        on_chunk(translated)

    # Persist to the SQLite cache, keyed by backend to avoid cross-contamination.
    try:
        from cache.store import save_to_cache
        save_to_cache(
            text,
            detected or cache_src,
            tgt,
            translated,
            domain_id=cache_domain,
        )
    except Exception:
        _logger.debug("Failed to cache NMT result (non-fatal)", exc_info=True)

    return detected, translated


# ── Public API ───────────────────────────────────────────


def translate(
    text: str,
    target_lang: str | None = None,
    source_lang: str | None = None,
    domain_id: str | None = None,
    on_chunk=None,
) -> str:
    """Translate *text* using the currently selected backend."""
    clear_notice()
    backend = get_active_backend()

    # ── NMT backends (Google / DeepL / Azure) ────────────
    if backend in _NMT_BACKENDS:
        _detected, translated = _nmt_translate(
            backend, text, target_lang, source_lang, domain_id, on_chunk,
        )
        return translated

    # ── Local NLLB model ─────────────────────────────────
    if backend == BACKEND_NLLB and _nllb_ready():
        from translate import nllb_backend
        return nllb_backend.translate(
            text, target_lang=target_lang, source_lang=source_lang,
            domain_id=domain_id, on_chunk=on_chunk,
        )

    # ── Cloud LLM (API) — default / fallback ─────────────
    from translate.llm_client import translate as api_translate
    return api_translate(
        text, target_lang=target_lang, source_lang=source_lang,
        domain_id=domain_id, on_chunk=on_chunk,
    )


def detect_and_translate(
    text: str,
    target_lang: str | None = None,
    domain_id: str | None = None,
    on_chunk=None,
) -> tuple[str, str]:
    """Detect the source language and translate using the selected backend."""
    clear_notice()
    backend = get_active_backend()

    # ── NMT backends (Google / DeepL / Azure) ────────────
    if backend in _NMT_BACKENDS:
        return _nmt_translate(
            backend, text, target_lang, None, domain_id, on_chunk,
        )

    # ── Local NLLB model ─────────────────────────────────
    if backend == BACKEND_NLLB and _nllb_ready():
        from translate import nllb_backend
        return nllb_backend.detect_and_translate(
            text, target_lang=target_lang, domain_id=domain_id, on_chunk=on_chunk,
        )

    # ── Cloud LLM (API) — default / fallback ─────────────
    from translate.llm_client import detect_and_translate as api_detect_and_translate
    return api_detect_and_translate(
        text, target_lang=target_lang, domain_id=domain_id, on_chunk=on_chunk,
    )


# ── Lifecycle ────────────────────────────────────────────


_NMT_LABELS = {
    BACKEND_GOOGLE: "Google Translate",
    BACKEND_DEEPL:  "DeepL API",
    BACKEND_AZURE:  "Microsoft Azure Translator",
}


def preload(backend: str | None = None) -> tuple[bool, str]:
    """Eagerly load *backend* (default: the active one) for the settings UI.

    Returns ``(ok, message)``. Never raises — the message is ready to display.
    """
    target = backend or get_active_backend()

    if target in _NMT_BACKENDS:
        label = _NMT_LABELS.get(target, target)
        return True, f"Используется {label}."

    if target != BACKEND_NLLB:
        return True, "Используется перевод через API."

    from translate.nllb_backend import NllbModelUnavailable, get_backend

    try:
        instance = get_backend()
        instance.ensure_loaded()
    except NllbModelUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # defensive: never break the settings dialog
        return False, f"Не удалось загрузить локальную модель: {exc}"

    device_line = f"Device: {instance.active_device.upper()}"
    notice = instance.take_notice()  # shown here, so the first translation won't repeat it
    if notice:
        device_line += f"\n{notice}"
    return True, (
        f"Модель загружена за {instance.load_seconds:.1f} с\n{instance.model_dir}\n{device_line}"
    )


def reset() -> None:
    """Reset both backends so new settings are picked up on the next request."""
    from translate.llm_client import reset_client as reset_api

    reset_api()
    try:
        from translate.nllb_backend import reset_client as reset_nllb
        reset_nllb()
    except Exception:
        _logger.exception("Failed to reset the NLLB backend (non-fatal)")
