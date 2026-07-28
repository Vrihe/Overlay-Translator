"""
translate/error_classification.py — LLM exception classification for resilience logic.

Distinguishes retryable (transient) errors from non-retryable (permanent) errors
for Anthropic and OpenAI (OpenRouter) SDK exceptions.
"""

import anthropic
import openai

# Transient errors — worth retrying on the same provider
RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)

# Permanent errors — retrying on the same provider will fail; switch to fallback
NON_RETRYABLE_EXCEPTIONS = (
    anthropic.AuthenticationError,
    anthropic.BadRequestError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    openai.AuthenticationError,
    openai.BadRequestError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
)


def is_retryable(exc: Exception) -> bool:
    """Return True if *exc* is a transient/retryable exception."""
    return isinstance(exc, RETRYABLE_EXCEPTIONS)
