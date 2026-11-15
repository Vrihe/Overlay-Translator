"""
audio/phrase_translator.py — recognised phrases → translated subtitles.

    translator = PhraseTranslator()
    translator.translated.connect(on_subtitle)     # (source, translation, notice)
    translator.start()
    translator.submit("Hello there.")              # from any thread
    ...
    translator.stop(); translator.wait()

Translation goes through ``translate.backend`` like every other text, with two
differences:
  • The local NLLB model drops sentences when it gets several at once, so for it a
    phrase is translated sentence by sentence.
  • Nothing is written to the database (``cache.store.memory_only``): subtitles must
    not flood the translation history.

A phrase that waits behind more than ``max_pending`` others is dropped: a slow
translator must catch up with the speech instead of drifting further behind.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque

from PyQt5.QtCore import QThread, pyqtSignal

import config

_logger = logging.getLogger("translator.subtitles")

#: Language assumed when the recognizer does not report one (``.en`` models: English).
SOURCE_LANG = "en"

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])")
#: Not sentence ends although they look like one.
_ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "e.g.", "i.e.", "etc.")


def split_sentences(text: str) -> list[str]:
    """Split recognised English speech into sentences (Whisper punctuates its output)."""
    sentences: list[str] = []
    for part in _SENTENCE_END.split(text.strip()):
        part = part.strip()
        if not part:
            continue
        if sentences and sentences[-1].lower().split()[-1] in _ABBREVIATIONS:
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def translate_phrase(text: str, source_lang: str = "") -> tuple[str, str]:
    """Translate one phrase with the active backend; returns ``(translation, notice)``.

    *source_lang* is the language of the speech as recognised ("" = English).
    """
    source = (source_lang or SOURCE_LANG).lower()
    from cache.store import memory_only
    from translate import backend

    if (config.TARGET_LANG or "").lower() == source:
        return text, ""  # nothing to translate: show the speech as recognised
    parts = split_sentences(text) if backend.get_active_backend() == backend.BACKEND_NLLB else [text]
    translated, notice = [], ""
    with memory_only():
        for part in parts:
            result = backend.translate(part, source_lang=source, domain_id=config.ACTIVE_DOMAIN)
            notice = backend.take_notice() or notice
            if result and result.strip():
                translated.append(result.strip())
    return " ".join(translated), notice


class PhraseTranslator(QThread):
    """Translates submitted phrases in order on its own thread."""

    #: (recognised text, translation, one-shot backend notice or "").
    translated = pyqtSignal(str, str, str)
    #: (recognised text, error message ready to display).
    failed = pyqtSignal(str, str)
    #: Interim result for the phrase still being spoken: (text so far, translation).
    partial_translated = pyqtSignal(str, str)

    def __init__(self, translate=translate_phrase, *, max_pending: int = 3, parent=None) -> None:
        super().__init__(parent)
        self._translate = translate
        self._max_pending = max_pending
        self._pending: deque[tuple[str, str]] = deque()  # (text, language)
        # Newest interim (text, language), or ""; translated only when no phrase is waiting.
        self._partial = ""
        self._wake = threading.Condition()
        self._stopping = False
        self.dropped_phrases = 0

    # ── Called from other threads ────────────────────────

    def submit(self, text: str, lang: str = "") -> None:
        """Queue a phrase; *lang* is its language as recognised ("" = not reported)."""
        with self._wake:
            self._partial = ""  # the phrase itself supersedes its interim text
            self._pending.append((text, lang))
            while len(self._pending) > self._max_pending:
                self._pending.popleft()
                self.dropped_phrases += 1
            self._wake.notify()

    def submit_partial(self, text: str, lang: str = "") -> None:
        """Queue interim text; a newer one replaces it, a waiting phrase goes first."""
        with self._wake:
            self._partial = (text, lang)
            self._wake.notify()

    def stop(self) -> None:
        """Ask the thread to finish; phrases still waiting are not translated."""
        with self._wake:
            self._stopping = True
            self._pending.clear()
            self._partial = ""
            self._wake.notify()

    # ── Thread body ──────────────────────────────────────

    def run(self) -> None:
        try:
            while True:
                with self._wake:
                    while not self._pending and not self._partial and not self._stopping:
                        self._wake.wait()
                    if self._stopping:
                        return
                    partial = not self._pending
                    if partial:
                        (text, lang), self._partial = self._partial, ""
                    else:
                        text, lang = self._pending.popleft()
                if partial:
                    self._translate_partial(text, lang)
                    continue
                try:
                    translation, notice = self._call(text, lang)
                except Exception as exc:  # never let an exception escape a QThread
                    _logger.warning("Subtitle translation failed: %s", type(exc).__name__, exc_info=True)
                    self.failed.emit(text, str(exc))
                    continue
                if translation:
                    self.translated.emit(text, translation, notice)
        finally:
            from cache.store import close_connection

            close_connection()

    def _call(self, text: str, lang: str):
        # The language is passed only when the recognizer reported one.
        return self._translate(text, lang) if lang else self._translate(text)

    def _translate_partial(self, text: str, lang: str = "") -> None:
        """Interim text: errors are not reported (the phrase itself will be), notices are dropped."""
        try:
            translation, _notice = self._call(text, lang)
        except Exception as exc:
            _logger.info("Interim subtitle translation failed: %s", type(exc).__name__)
            return
        with self._wake:
            stale = bool(self._pending) or self._stopping
        if translation and not stale:
            self.partial_translated.emit(text, translation)
