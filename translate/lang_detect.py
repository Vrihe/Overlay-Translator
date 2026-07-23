"""
translate/lang_detect.py — automatic source-language detection.

Provides two interchangeable backends behind a common interface:
  • LangidDetector  — offline ML model (fast, deterministic, free)
  • LLMDetector     — uses the already-configured LLM client (more
                      accurate on short / noisy game-chat text, but
                      adds latency and cost)

Which backend is active is controlled by ``config.LANG_DETECT_ENGINE``.
"""

from abc import ABC, abstractmethod
import re


# ── Script detection (Unicode-based, not ML) ─────────────

_CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')
_LATIN_RE = re.compile(r'[a-zA-Z]')


def detect_script(text: str) -> str:
    """Determine the writing script of *text* by counting Unicode code points.

    Returns ``'cyrillic'``, ``'latin'``, or ``'unknown'`` (when the text
    contains neither — e.g. pure digits / punctuation).

    This is a deterministic, zero-cost check that is not subject to the
    statistical errors of ML classifiers like ``langid``.
    """
    cyrillic_count = len(_CYRILLIC_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    total = cyrillic_count + latin_count
    if total == 0:
        return "unknown"
    return "cyrillic" if cyrillic_count / total > 0.5 else "latin"


def detect_source_lang(text: str, detector: 'LangDetector',
                       cyrillic_default: str = "ru") -> str | None:
    """Two-stage language detection: script check → ML detector.

    1. If the text is predominantly Cyrillic, return *cyrillic_default*
       immediately (``langid`` is unreliable on Cyrillic — it confuses
       ru / uk / bg and sometimes misclassifies Cyrillic as Latin).
    2. For Latin or unknown scripts, delegate to *detector* (langid or LLM).

    Parameters
    ----------
    text : str
        Text to analyse.
    detector : LangDetector
        The ML/LLM detector to use for non-Cyrillic text.
    cyrillic_default : str
        ISO 639-1 code to return when script is Cyrillic.
        Defaults to ``"ru"``.

    Returns
    -------
    str or None
        Detected language code, or ``None`` if the detector is not
        confident (caller should fall back to ``config.SOURCE_LANG``).
    """
    script = detect_script(text)
    if script == "cyrillic":
        return cyrillic_default
    # latin / unknown — use the ML/LLM detector as before.
    return detector.detect(text)


class LangDetector(ABC):
    """Abstract base for language detectors."""

    @abstractmethod
    def detect(self, text: str) -> str | None:
        """Return an ISO 639-1 language code (e.g. ``'en'``, ``'de'``, ``'ru'``).

        Returns ``None`` if the detector is not confident in its result,
        signalling the caller to use the fallback source language.
        """


# ── Langid backend ───────────────────────────────────────

class LangidDetector(LangDetector):
    """Offline language detection via the *langid* library.

    langid uses a pre-trained Naive Bayes model over byte n-grams.
    It is deterministic (no random seed) and works without any network
    access, making it the preferred default for this application.

    If the classifier's confidence (log-probability) is below
    ``LANGID_CONFIDENCE_THRESHOLD`` the result is considered unreliable
    and ``None`` is returned so the caller can fall back to a fixed
    source language.
    """

    # langid returns a negative log-probability.  More negative values
    # indicate higher confidence (e.g. -150 for a clear English sentence).
    # Values near 0 or positive indicate low confidence (noisy/garbled
    # OCR output, mixed scripts).  Threshold of -20 filters out
    # clearly unreliable results while keeping normal detections.
    _CONFIDENCE_THRESHOLD = -20.0

    def __init__(self):
        import langid
        self._langid = langid

    def detect(self, text: str) -> str | None:
        lang, confidence = self._langid.classify(text)
        if confidence > self._CONFIDENCE_THRESHOLD:
            return None  # unreliable — caller should use fallback
        return lang


# ── LLM backend ──────────────────────────────────────────

class LLMDetector(LangDetector):
    """Language detection via the active LLM provider.

    Sends a short, strictly formatted request to the LLM asking it to
    return only the ISO 639-1 code of the detected language.  Re-uses
    the client already configured in ``translate.llm_client``.
    """

    def __init__(self):
        # Import lazily to avoid circular imports at module level.
        from translate.llm_client import _get_client
        self._get_client = _get_client

    def detect(self, text: str) -> str:
        client, provider = self._get_client()

        system_prompt = (
            "You are a language detector. "
            "Reply with ONLY the ISO 639-1 two-letter language code "
            "(e.g. en, de, ru, pl). Nothing else."
        )
        user_prompt = f"Detect the language:\n\n{text}"

        if provider == "openrouter":
            import config
            response = client.chat.completions.create(
                model=config.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                extra_headers={
                    "HTTP-Referer": "https://github.com/your-username/overlay-translator",
                    "X-Title": "Overlay Translator",
                },
            )
            result = response.choices[0].message.content.strip().lower()
        else:
            # Anthropic
            message = client.messages.create(
                model="claude-haiku-4-20250414",
                max_tokens=8,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            result = message.content[0].text.strip().lower()

        # Sanitise: take only the first two-letter token.
        code = result[:2]
        return code


# ── Factory ──────────────────────────────────────────────

_detector_cache: dict[str, LangDetector] = {}


def get_detector(engine: str) -> LangDetector:
    """Return a (cached) ``LangDetector`` instance for the given *engine*.

    Parameters
    ----------
    engine : str
        ``"langid"`` or ``"llm"``.  The value ``"off"`` should be
        handled by the caller (fall back to a fixed source language)
        *before* calling this function.

    Raises
    ------
    ValueError
        If *engine* is not a recognised backend name.
    """
    if engine in _detector_cache:
        return _detector_cache[engine]

    if engine == "langid":
        detector = LangidDetector()
    elif engine == "llm":
        detector = LLMDetector()
    else:
        raise ValueError(f"Unknown lang-detect engine: {engine!r}")

    _detector_cache[engine] = detector
    return detector
