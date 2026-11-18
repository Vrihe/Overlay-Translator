"""
audio/session.py — SubtitleSession: capture → speech recognition → translation.

    session = SubtitleSession()
    session.subtitle.connect(window.add_line)        # (recognised text, translation)
    session.status.connect(window.set_status)        # (message, "info" | "ok" | "warn" | "error")
    session.running_changed.connect(...)
    session.start()
    ...
    session.stop()

Lives on the GUI thread and owns the two workers (``SttWorker``, ``PhraseTranslator``)
and the capture. Settings are read at ``start()``: a change applies to the next start.
The capture starts only when the speech model is loaded, so no audio piles up (and is
then dropped as "too late") while the model loads.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore import QObject, pyqtSignal

import config
from i18n import tr

_logger = logging.getLogger("translator.subtitles")


#: The model used instead of an English-only one when another speech language is chosen.
MULTILINGUAL_MODEL = "small"


def _default_recognizer():
    """The recognizer for the saved settings. Raises ``SttModelUnavailable``.

    An English-only model (``*.en``) fed speech in another language does not fail: it
    invents English text that has nothing to do with what is said. So with another speech
    language chosen, the multilingual model is used when it is on disk (the recognizer's
    ``start_notice`` says so) and the start is refused when it is not.
    """
    from audio import stt

    name = getattr(config, "SUBTITLES_MODEL", "") or stt.DEFAULT_MODEL
    language = (getattr(config, "SUBTITLES_LANGUAGE", "en") or "en").lower()
    notice = ""
    if language != "en" and not stt.is_multilingual(name):
        if stt.resolve_model_dir(MULTILINGUAL_MODEL) is None:
            raise stt.SttModelUnavailable(
                tr(
                    "Модель {name} понимает только английский. Для другого языка речи скачайте "
                    "в настройках многоязычную модель {model} или выберите английский.",
                    name=name,
                    model=MULTILINGUAL_MODEL,
                )
            )
        notice = tr(
            "Модель {name} понимает только английский: используется многоязычная {model}.",
            name=name,
            model=MULTILINGUAL_MODEL,
        )
        name = MULTILINGUAL_MODEL
    recognizer = stt.SpeechRecognizer(
        name,
        device=getattr(config, "SUBTITLES_STT_DEVICE", "auto") or "auto",
        language=language,
        skip_foreign=bool(getattr(config, "SUBTITLES_SKIP_FOREIGN", False)),
        low_vram=bool(getattr(config, "SUBTITLES_LOW_VRAM", False)),
    )
    recognizer.start_notice = notice
    return recognizer


#: Seconds of new speech between two interim subtitles (the "streaming" setting).
PARTIAL_INTERVAL_S = 1.0
#: After the first "recognition is behind" warning, repeat it every this many dropped phrases.
DROPPED_REPORT_EVERY = 10


def _default_capture(on_audio):
    from audio.capture import LoopbackCapture

    return LoopbackCapture(on_audio, getattr(config, "SUBTITLES_DEVICE", "") or "")


class SubtitleSession(QObject):
    #: (recognised text, translation).
    subtitle = pyqtSignal(str, str)
    #: Interim (text so far, translation) of the phrase still being spoken; only with
    #: config.SUBTITLES_STREAMING. The next one or the ``subtitle`` of the phrase replaces it.
    subtitle_partial = pyqtSignal(str, str)
    #: (message ready to display, kind: "info" | "ok" | "warn" | "error").
    status = pyqtSignal(str, str)
    running_changed = pyqtSignal(bool)

    def __init__(self, *, recognizer_factory=None, capture_factory=None, translate=None, parent=None) -> None:
        super().__init__(parent)
        self._recognizer_factory = recognizer_factory or _default_recognizer
        self._capture_factory = capture_factory or _default_capture
        self._translate = translate
        self._stt = None
        self._last_stt = None  # kept after stop() so stats() still answers
        self._translator = None
        self._capture = None
        self._run_id = 0  # results of an earlier run are ignored
        self._start_notice = ""  # what the recognizer factory had to say about this run
        # A running QThread must stay referenced until it has finished.
        self._retired: set = set()

    @property
    def is_running(self) -> bool:
        return self._stt is not None

    def start(self) -> None:
        if self.is_running:
            return
        from audio.phrase_translator import PhraseTranslator
        from audio.stt import SttModelUnavailable
        from audio.worker import SttWorker

        try:
            recognizer = self._recognizer_factory()
        except SttModelUnavailable as exc:
            # Not started: tell every switch first, then say why (like a failed load).
            self.running_changed.emit(False)
            self.status.emit(str(exc), "error")
            return
        self._start_notice = getattr(recognizer, "start_notice", "") or ""
        self._run_id += 1
        run = self._run_id
        streaming = bool(getattr(config, "SUBTITLES_STREAMING", False))
        self._stt = SttWorker(recognizer, partial_interval_s=PARTIAL_INTERVAL_S if streaming else 0.0)
        self._translator = PhraseTranslator(self._translate) if self._translate else PhraseTranslator()
        translator = self._translator
        self._stt.ready.connect(lambda device, notice: self._on_ready(run, device, notice))
        self._stt.failed.connect(lambda message: self._on_failed(run, message))
        self._stt.phrase_dropped.connect(lambda total: self._on_dropped(run, total))
        self._stt.phrase_recognized.connect(
            lambda text, _start, _end, lang: translator.submit(text, lang) if run == self._run_id else None
        )
        self._stt.partial_recognized.connect(
            lambda text, lang: translator.submit_partial(text, lang) if run == self._run_id else None
        )
        translator.partial_translated.connect(
            lambda source, text: self.subtitle_partial.emit(source, text) if run == self._run_id else None
        )
        translator.translated.connect(lambda source, text, notice: self._on_translated(run, source, text, notice))
        translator.failed.connect(lambda _source, message: self._on_translation_failed(run, message))
        self.status.emit(tr("Загрузка модели распознавания речи…"), "info")
        self._stt.start()
        translator.start()
        self.running_changed.emit(True)

    def stop(self) -> None:
        if not self.is_running:
            return
        self._run_id += 1
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.stop()
        for thread in (self._stt, self._translator):
            thread.stop()
            self._retire(thread)
        self._last_stt = self._stt
        self._stt = self._translator = None
        self.running_changed.emit(False)

    def _retire(self, thread) -> None:
        self._retired.add(thread)
        thread.finished.connect(lambda t=thread: self._retired.discard(t))
        if thread.isFinished():
            self._retired.discard(thread)

    # ── Worker signals (GUI thread) ──────────────────────

    def _on_ready(self, run: int, device: str, notice: str) -> None:
        if run != self._run_id:
            return
        from audio.capture import CaptureUnavailable, display_name

        capture = self._capture_factory(self._stt.feed)
        try:
            capture.start()
        except CaptureUnavailable as exc:
            self.stop()
            self.status.emit(str(exc), "error")
            return
        except Exception as exc:
            _logger.exception("Audio capture failed to start")
            self.stop()
            self.status.emit(tr("Не удалось начать захват звука: {error}", error=exc), "error")
            return
        self._capture = capture
        lines = [tr("Слушаю: {device}", device=display_name(capture.device_name))]
        if getattr(capture, "fell_back", False):
            lines.append(tr("Выбранное устройство не найдено, используется устройство по умолчанию."))
        if self._start_notice:
            lines.append(self._start_notice)
        if notice:
            lines.append(notice)
        self.status.emit("\n".join(lines), "ok" if len(lines) == 1 else "warn")
        _logger.info("Subtitles started (speech recognition on %s)", device)

    def stats(self) -> dict:
        """Numbers of the running (or just stopped) session; empty when never started."""
        stt = self._stt or self._last_stt
        if stt is None:
            return {}
        done = stt.recognized_phrases
        return {
            "recognized": done,
            "dropped": stt.dropped_phrases,
            "avg_decode_s": stt.decode_seconds / done if done else 0.0,
            "max_behind_s": stt.max_behind_s,
        }

    def _on_dropped(self, run: int, total: int) -> None:
        """Say once, then every ``DROPPED_REPORT_EVERY`` phrases, that recognition falls behind."""
        if run != self._run_id or (total != 1 and total % DROPPED_REPORT_EVERY):
            return
        self.status.emit(
            tr(
                "Распознавание не успевает за речью, пропущено фраз: {count}. "
                "Выберите модель поменьше или выключите потоковый режим.",
                count=total,
            ),
            "warn",
        )

    def _on_failed(self, run: int, message: str) -> None:
        if run != self._run_id:
            return
        self.stop()  # first: a status that arrives while stopped is the reason it stopped
        self.status.emit(message, "error")

    def _on_translated(self, run: int, source: str, translation: str, notice: str) -> None:
        if run != self._run_id:
            return
        if notice:
            self.status.emit(notice, "warn")
        self.subtitle.emit(source, translation)

    def _on_translation_failed(self, run: int, message: str) -> None:
        if run == self._run_id:
            first_line = message.strip().splitlines()[0] if message.strip() else ""
            self.status.emit(tr("Ошибка перевода: {error}", error=first_line), "error")
