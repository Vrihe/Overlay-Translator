"""
translate/backend.py — chooses between the API and the local NLLB translator.

Exposes exactly the surface ``translate.llm_client`` does, so call sites only
swap the import:

    translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None) -> str
    detect_and_translate(text, target_lang=None, domain_id=None, on_chunk=None) -> (lang, text)

Which backend runs is read from ``config.TRANSLATION_BACKEND`` on every call, so
a settings change takes effect immediately without restarting the app.

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
BACKEND_NLLB = "nllb"

#: (id, human label) — consumed by ui/settings_dialog.
BACKENDS: list[tuple[str, str]] = [
    (BACKEND_API, "API (Anthropic / OpenRouter)"),
    (BACKEND_NLLB, "Локальная модель (NLLB)"),
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
    return value if value in (BACKEND_API, BACKEND_NLLB) else BACKEND_API


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

    if get_active_backend() == BACKEND_NLLB and _nllb_ready():
        from translate import nllb_backend
        return nllb_backend.translate(
            text, target_lang=target_lang, source_lang=source_lang,
            domain_id=domain_id, on_chunk=on_chunk,
        )

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

    if get_active_backend() == BACKEND_NLLB and _nllb_ready():
        from translate import nllb_backend
        return nllb_backend.detect_and_translate(
            text, target_lang=target_lang, domain_id=domain_id, on_chunk=on_chunk,
        )

    from translate.llm_client import detect_and_translate as api_detect_and_translate
    return api_detect_and_translate(
        text, target_lang=target_lang, domain_id=domain_id, on_chunk=on_chunk,
    )


# ── Lifecycle ────────────────────────────────────────────


def preload(backend: str | None = None) -> tuple[bool, str]:
    """Eagerly load *backend* (default: the active one) for the settings UI.

    Returns ``(ok, message)``. Never raises — the message is ready to display.
    """
    target = backend or get_active_backend()

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
