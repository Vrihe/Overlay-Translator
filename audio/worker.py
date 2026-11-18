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

Two threads: the QThread recognises phrases, a helper thread (``stt-segmenter``) runs the
VAD and cuts the stream into phrases. A long decode therefore never stops the VAD from
reading the audio, and the lag of a phrase is measured against the real stream position.

When recognition is slower than speech (a CPU under load), phrases pile up. A phrase
that is already more than ``max_lag_s`` behind the stream is dropped instead of being
recognised: a subtitle that late is useless, and skipping it lets the worker catch up.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

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
        self._chunks: queue.Queue = queue.Queue()  # audio → segmenter thread
        self._jobs: queue.Queue = queue.Queue()  # phrases → recognition (this QThread)
        self._busy = False  # recognition in progress (interim text waits for it)
        self.recognized_phrases = 0
        self.decode_seconds = 0.0  # total time spent recognising final phrases
        self.max_behind_s = 0.0  # worst "audio that arrived after the phrase closed" seen
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

        segmenter_thread = threading.Thread(target=self._segment_loop, name="stt-segmenter", daemon=True)
        segmenter_thread.start()
        while True:
            job = self._jobs.get()
            if job is _STOP:
                break
            kind, payload, check_lag = job
            self._busy = True
            try:
                if kind == "partial":
                    self._recognize_partial(payload)
                else:
                    self._recognize([payload], check_lag)
            finally:
                self._busy = False
        segmenter_thread.join(2.0)

    # ── Segmenter thread ─────────────────────────────────

    def _segment_loop(self) -> None:
        try:
            while True:
                chunk = self._chunks.get()
                if chunk is _STOP:
                    for phrase in self._segmenter.flush():
                        self._jobs.put(("phrase", phrase, False))
                    return
                try:
                    phrases = self._segmenter.feed(chunk)
                except Exception:
                    _logger.exception("Segmenting audio failed")
                    continue
                if phrases:
                    self._partial_len = 0
                for phrase in phrases:
                    self._jobs.put(("phrase", phrase, True))
                if self._partial_step and self._chunks.empty() and self._jobs.empty() and not self._busy:
                    self._queue_partial()
        finally:
            self._jobs.put(_STOP)

    def _queue_partial(self) -> None:
        audio = self._segmenter.partial()
        if audio is None:
            self._partial_len = 0
            return
        if len(audio) - self._partial_len < self._partial_step:
            return
        self._partial_len = len(audio)
        self._jobs.put(("partial", audio, False))

    # ── Recognition ──────────────────────────────────────

    def _recognize_partial(self, audio) -> None:
        try:
            text = self._recognizer.transcribe(audio)
        except Exception:
            _logger.exception("Interim speech recognition failed")
            return
        if text:
            self.partial_recognized.emit(text, self._language())

    def _recognize(self, phrases, check_lag: bool) -> None:
        for phrase in phrases:
            behind = self._lag(phrase)
            if check_lag and behind > self._max_lag_s:
                self.dropped_phrases += 1
                _logger.warning("STT is %.1fs behind, phrase dropped", behind)
                continue
            self.max_behind_s = max(self.max_behind_s, behind)
            t0 = time.perf_counter()
            try:
                text = self._recognizer.transcribe(phrase.audio)
            except Exception:
                _logger.exception("Speech recognition failed for one phrase")
                continue
            decode = time.perf_counter() - t0
            self.recognized_phrases += 1
            self.decode_seconds += decode
            _logger.info(
                "STT | phrase %.1fs | %.1fs behind the stream | decoded in %.2fs",
                len(phrase.audio) / SAMPLE_RATE,
                behind,
                decode,
            )
            if text:
                self.phrase_recognized.emit(text, phrase.start, phrase.end, self._language())

    def _language(self) -> str:
        return getattr(self._recognizer, "last_language", "") or ""

    def _lag(self, phrase) -> float:
        """Seconds of audio that arrived after *phrase* was closed."""
        with self._fed_lock:
            fed = self._fed_samples
        return fed / SAMPLE_RATE - phrase.closed_at
