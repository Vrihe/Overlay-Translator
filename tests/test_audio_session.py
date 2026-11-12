"""
tests/test_audio_session.py — audio/session.py: SubtitleSession with a fake recognizer,
a fake capture and a fake translate function (no model, no sound device, no network).
"""

import os
import sys
import time
import unittest
from unittest import mock

import numpy as np
from PyQt5.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from audio import segmenter
from audio.capture import CaptureUnavailable
from audio.segmenter import SAMPLE_RATE
from audio.session import SubtitleSession
from audio.stt import SttModelUnavailable

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


def _pump(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    return condition()


class _LoudnessVad:
    def prob(self, frame):
        return 1.0 if float(np.abs(frame).mean()) > 0.5 else 0.0


class _FakeRecognizer:
    active_device = "cpu"

    def __init__(self, load_error=None, notice=""):
        self._load_error = load_error
        self._notice = notice
        self.calls = 0

    def ensure_loaded(self):
        if self._load_error:
            raise self._load_error

    def take_notice(self):
        return self._notice

    def transcribe(self, audio):
        self.calls += 1
        return f"phrase {self.calls}"


class _FakeCapture:
    def __init__(self, on_audio, start_error=None, fell_back=False):
        self.on_audio = on_audio
        self.start_error = start_error
        self.fell_back = fell_back
        self.device_name = "Speakers (Fake) [Loopback]"
        self.started = self.stopped = False

    def start(self):
        if self.start_error:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stopped = True

    def say(self):
        """One phrase: speech followed by a closing pause."""
        self.on_audio(np.ones(SAMPLE_RATE, dtype="float32"))
        self.on_audio(np.zeros(SAMPLE_RATE, dtype="float32"))


class _SessionCase(unittest.TestCase):
    def setUp(self):
        # The session builds its own Segmenter: give it a VAD that needs no model.
        patcher = mock.patch.object(segmenter, "SileroVad", _LoudnessVad)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.captures = []
        self.recognizer = _FakeRecognizer()
        self.capture_kwargs = {}
        self.translate = lambda text: (text.upper(), "")

    def make(self):
        def capture_factory(on_audio):
            self.captures.append(_FakeCapture(on_audio, **self.capture_kwargs))
            return self.captures[-1]

        session = SubtitleSession(
            recognizer_factory=lambda: self.recognizer,
            capture_factory=capture_factory,
            translate=lambda text: self.translate(text),
        )
        self.subtitles, self.statuses, self.running = [], [], []
        session.subtitle.connect(lambda source, text: self.subtitles.append((source, text)))
        session.status.connect(lambda message, kind: self.statuses.append((message, kind)))
        session.running_changed.connect(self.running.append)
        self.addCleanup(self.finish, session)
        return session

    def finish(self, session):
        session.stop()
        self.assertTrue(_pump(lambda: not session._retired))


class TestSubtitleSession(_SessionCase):
    def test_speech_becomes_a_translated_subtitle(self):
        session = self.make()
        session.start()
        self.assertTrue(session.is_running)
        self.assertEqual(self.statuses[0][1], "info")  # "loading the model"
        self.assertTrue(_pump(lambda: bool(self.captures)))
        self.assertTrue(self.captures[0].started)
        self.assertEqual(self.statuses[-1], ("Слушаю: Speakers (Fake)", "ok"))
        self.captures[0].say()
        self.assertTrue(_pump(lambda: len(self.subtitles) == 1))
        self.assertEqual(self.subtitles, [("phrase 1", "PHRASE 1")])
        self.assertEqual(self.running, [True])

    def test_streaming_setting_adds_interim_subtitles(self):
        session = self.make()
        partials = []
        session.subtitle_partial.connect(lambda source, text: partials.append((source, text)))
        with mock.patch.object(type(config), "SUBTITLES_STREAMING", new_callable=mock.PropertyMock, return_value=True):
            session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        self.captures[0].on_audio(np.zeros(8000, dtype="float32"))
        self.captures[0].on_audio(np.ones(24000, dtype="float32"))  # 1.5 s of speech, no pause yet
        self.assertTrue(_pump(lambda: len(partials) == 1))
        self.assertEqual(partials, [("phrase 1", "PHRASE 1")])
        self.assertEqual(self.subtitles, [])
        self.captures[0].on_audio(np.zeros(16000, dtype="float32"))
        self.assertTrue(_pump(lambda: len(self.subtitles) == 1))

    def test_stop_ends_capture_and_both_threads(self):
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        session.stop()
        self.assertFalse(session.is_running)
        self.assertTrue(self.captures[0].stopped)
        self.assertEqual(self.running, [True, False])
        self.assertTrue(_pump(lambda: not session._retired))
        session.stop()  # repeatable
        self.assertEqual(self.running, [True, False])

    def test_results_of_a_stopped_run_are_ignored(self):
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        self.captures[0].on_audio(np.ones(SAMPLE_RATE, dtype="float32"))  # a phrase in progress
        session.stop()  # the worker still recognises it while finishing
        self.assertTrue(_pump(lambda: not session._retired))
        self.assertEqual(self.subtitles, [])

    def test_it_can_be_started_again(self):
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: len(self.captures) == 1))
        session.stop()
        session.start()
        self.assertTrue(_pump(lambda: len(self.captures) == 2))
        self.captures[1].say()
        self.assertTrue(_pump(lambda: len(self.subtitles) == 1))

    def test_start_twice_is_one_run(self):
        session = self.make()
        session.start()
        session.start()
        self.assertEqual(self.running, [True])

    def test_missing_model_stops_with_the_reason(self):
        self.recognizer = _FakeRecognizer(load_error=SttModelUnavailable("model small.en not found"))
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: self.running == [True, False]))
        self.assertEqual(self.statuses[-1], ("model small.en not found", "error"))
        self.assertEqual(self.captures, [])  # nothing was captured without a model
        self.assertFalse(session.is_running)

    def test_capture_failure_stops_with_the_reason(self):
        self.capture_kwargs = {"start_error": CaptureUnavailable("no output device")}
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: self.running == [True, False]))
        self.assertEqual(self.statuses[-1], ("no output device", "error"))

    def test_fallbacks_are_reported_as_a_warning(self):
        self.recognizer = _FakeRecognizer(notice="CUDA unavailable")
        self.capture_kwargs = {"fell_back": True}
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        message, kind = self.statuses[-1]
        self.assertEqual(kind, "warn")
        self.assertIn("CUDA unavailable", message)
        self.assertIn("по умолчанию", message)

    def test_translation_error_keeps_the_session_running(self):
        def translate(text):
            raise RuntimeError("quota exceeded\ntraceback detail")

        self.translate = translate
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        self.captures[0].say()
        self.assertTrue(_pump(lambda: self.statuses[-1][1] == "error"))
        self.assertEqual(self.statuses[-1][0], "Ошибка перевода: quota exceeded")
        self.assertTrue(session.is_running)

    def test_backend_notice_is_shown_with_the_subtitle(self):
        self.translate = lambda text: (text.upper(), "translated through the API")
        session = self.make()
        session.start()
        self.assertTrue(_pump(lambda: bool(self.captures)))
        self.captures[0].say()
        self.assertTrue(_pump(lambda: len(self.subtitles) == 1))
        self.assertEqual(self.statuses[-1], ("translated through the API", "warn"))


if __name__ == "__main__":
    unittest.main()
