"""
audio/worker.py — SttWorker: the thread that turns a live audio stream into text.

    worker = SttWorker()
    worker.phrase_recognized.connect(on_text)   # (text, start_s, end_s, language)
    worker.start()
    worker.feed(chunk)        # 16 kHz mono float32, from any thread (e.g. a capture callback)
    ...
    worker.stop(); worker.wait()

The owner keeps a reference to the worker until it has finished (a dropped running
QThread aborts the process). Widgets are never touched here: results leave through
signals only.

Interim results (``partial_interval_s > 0``, the "streaming" setting): while a phrase is
still being spoken, the audio collected so far is recognised again every
``partial_interval_s`` seconds of new speech and leaves through ``partial_recognized``.
It is only done when no audio is waiting, so it never delays the final phrases.

When recognition is slower than speech (a CPU under load), phrases pile up. A phrase
that is already more than ``max_lag_s`` behind the stream is dropped instead of being
recognised: a subtitle that late is useless, and skipping it lets the worker catch up.
"""

from __future__ import annotations

import logging
import queue
import threading

from PyQt5.QtCore import QThread, pyqtSignal

from audio.segmenter import SAMPLE_RATE, Segmenter
from audio.stt import SpeechRecognizer, SttModelUnavailable

_logger = logging.getLogger("translator.stt")

_STOP = object()


class SttWorker(QThread):
    """Segments the audio it is fed and recognises each phrase."""

    #: The model is loaded: (device "cuda" | "cpu", one-shot notice or "").
    ready = pyqtSignal(str, str)
    #: One recognised phrase: (text, start, end, language); times in seconds from the start
    #: of the stream, language as reported by the recognizer ("" when unknown).
    phrase_recognized = pyqtSignal(str, float, float, str)
    #: (text, language) of the phrase in progress so far; replaced by the next one or by the
    #: phrase itself.
    partial_recognized = pyqtSignal(str, str)
    #: The model cannot be loaded; the worker stops. The message is ready to display.
    failed = pyqtSignal(str)

    def __init__(
        self,
        recognizer=None,
        segmenter=None,
        *,
        max_lag_s: float = 6.0,
        partial_interval_s: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._recognizer = recognizer if recognizer is not None else SpeechRecognizer()
        self._segmenter = segmenter if segmenter is not None else Segmenter()
        self._max_lag_s = max_lag_s
        self._partial_step = int(partial_interval_s * SAMPLE_RATE)  # 0 = no interim results
        self._partial_len = 0  # samples of the phrase in progress already shown
        self._chunks: queue.Queue = queue.Queue()
        self._fed_samples = 0
        self._fed_lock = threading.Lock()
        self.dropped_phrases = 0

    # ── Called from other threads ────────────────────────

    def feed(self, chunk) -> None:
        """Queue audio for recognition. Thread-safe; never blocks."""
        with self._fed_lock:
            self._fed_samples += len(chunk)
        self._chunks.put(chunk)

    def stop(self) -> None:
        """Ask the thread to finish; the phrase in progress is still recognised."""
        self._chunks.put(_STOP)

    # ── Thread body ──────────────────────────────────────

    def run(self) -> None:
        try:
            self._recognizer.ensure_loaded()
        except SttModelUnavailable as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # never let an exception escape a QThread
            _logger.exception("Speech model failed to load")
            self.failed.emit(str(exc))
            return
        self.ready.emit(self._recognizer.active_device, self._recognizer.take_notice())

        while True:
            chunk = self._chunks.get()
            if chunk is _STOP:
                self._recognize(self._segmenter.flush(), check_lag=False)
                return
            phrases = self._segmenter.feed(chunk)
            if phrases:
                self._partial_len = 0
            self._recognize(phrases, check_lag=True)
            if self._partial_step and self._chunks.empty():
                self._recognize_partial()

    def _recognize_partial(self) -> None:
        audio = self._segmenter.partial()
        if audio is None:
            self._partial_len = 0
            return
        if len(audio) - self._partial_len < self._partial_step:
            return
        self._partial_len = len(audio)
        try:
            text = self._recognizer.transcribe(audio)
        except Exception:
            _logger.exception("Interim speech recognition failed")
            return
        if text:
            self.partial_recognized.emit(text, self._language())

    def _recognize(self, phrases, check_lag: bool) -> None:
        for phrase in phrases:
            if check_lag and self._lag(phrase) > self._max_lag_s:
                self.dropped_phrases += 1
                _logger.warning("STT is %.1fs behind, phrase dropped", self._lag(phrase))
                continue
            try:
                text = self._recognizer.transcribe(phrase.audio)
            except Exception:
                _logger.exception("Speech recognition failed for one phrase")
                continue
            if text:
                self.phrase_recognized.emit(text, phrase.start, phrase.end, self._language())

    def _language(self) -> str:
        return getattr(self._recognizer, "last_language", "") or ""

    def _lag(self, phrase) -> float:
        """Seconds of audio that arrived after *phrase* was closed."""
        with self._fed_lock:
            fed = self._fed_samples
        return fed / SAMPLE_RATE - phrase.closed_at
