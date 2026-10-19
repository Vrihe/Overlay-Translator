"""
translate/error_classification.py — LLM exception classification for resilience logic.

Identifies retryable (transient) errors among Anthropic and OpenAI (OpenRouter)
SDK exceptions; anything else is treated as permanent.
"""

# openai and anthropic are imported lazily inside _ensure_loaded() so that
# importing this module does not trigger heavy SDK initialization at startup.
_retryable_types: tuple | None = None


def _ensure_loaded() -> None:
    """Build exception-type tuples on first use (lazy import of openai/anthropic)."""
    global _retryable_types
    if _retryable_types is not None:
        return
    import anthropic
    import openai

    # Transient errors — worth retrying on the same provider
    _retryable_types = (
        anthropic.RateLimitError,
        anthropic.APITimeoutError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


def is_retryable(exc: Exception) -> bool:
    """Return True if *exc* is a transient/retryable exception."""
    _ensure_loaded()
    return isinstance(exc, _retryable_types)
