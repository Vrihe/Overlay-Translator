"""
tests/test_audio_worker.py — audio/worker.py: SttWorker with a fake recognizer and VAD.

The worker runs as a real QThread; results are collected through its signals.
"""

import os
import sys
import threading
import time
import unittest

import numpy as np
from PyQt5.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audio.segmenter import SAMPLE_RATE, Segmenter
from audio.stt import SttModelUnavailable
from audio.worker import SttWorker

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class _LoudnessVad:
    def prob(self, frame):
        return 1.0 if float(np.abs(frame).mean()) > 0.5 else 0.0


class _FakeRecognizer:
    active_device = "cpu"

    def __init__(self, notice="", load_error=None, fail_on=()):
        self._notice = notice
        self._load_error = load_error
        self._fail_on = set(fail_on)
        self.loaded = False
        self.calls = 0
        self.threads = set()
        self.gate = None  # when set, transcribe() blocks until it is released

    def ensure_loaded(self):
        if self._load_error:
            raise self._load_error
        self.loaded = True

    def take_notice(self):
        notice, self._notice = self._notice, ""
        return notice

    def transcribe(self, audio):
        self.calls += 1
        self.threads.add(threading.get_ident())
        if self.gate is not None:
            self.gate.wait(5)
        if self.calls in self._fail_on:
            raise RuntimeError("decoder exploded")
        return f"phrase {self.calls}"


def _speech(seconds):
    return np.ones(int(seconds * SAMPLE_RATE), dtype="float32")


def _silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype="float32")


def _pump(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    return condition()


class TestSttWorker(unittest.TestCase):
    def start(self, recognizer, **kwargs):
        worker = SttWorker(recognizer, Segmenter(_LoudnessVad()), **kwargs)
        self.phrases, self.ready, self.failed = [], [], []
        self.languages = []
        worker.phrase_recognized.connect(lambda text, start, end, lang: self.phrases.append((text, start, end)))
        worker.phrase_recognized.connect(lambda text, start, end, lang: self.languages.append(lang))
        worker.ready.connect(lambda device, notice: self.ready.append((device, notice)))
        worker.failed.connect(self.failed.append)
        worker.start()
        self.addCleanup(self.finish, worker)
        return worker

    def finish(self, worker):
        worker.stop()
        self.assertTrue(worker.wait(5000))

    def test_phrases_come_out_in_order_with_times(self):
        recognizer = _FakeRecognizer(notice="on CPU")
        worker = self.start(recognizer)
        worker.feed(np.concatenate([_silence(0.5), _speech(1), _silence(1), _speech(1), _silence(1)]))
        self.assertTrue(_pump(lambda: len(self.phrases) == 2))
        self.assertEqual([p[0] for p in self.phrases], ["phrase 1", "phrase 2"])
        self.assertAlmostEqual(self.phrases[0][2], 1.5, delta=0.05)
        self.assertLess(self.phrases[0][2], self.phrases[1][1])
        self.assertEqual(self.ready, [("cpu", "on CPU")])
        # Recognition runs on the worker thread, never on the caller's.
        self.assertNotIn(threading.get_ident(), recognizer.threads)

    def test_interim_text_while_the_phrase_is_still_spoken(self):
        worker = self.start(_FakeRecognizer(), partial_interval_s=1.0)
        partials = []
        worker.partial_recognized.connect(lambda text, lang: partials.append(text))
        worker.feed(np.concatenate([_silence(0.5), _speech(1.2)]))
        self.assertTrue(_pump(lambda: len(partials) == 1))
        worker.feed(_speech(0.3))  # less than a second of new speech: nothing new
        worker.feed(_speech(1.0))
        self.assertTrue(_pump(lambda: len(partials) == 2))
        self.assertEqual(self.phrases, [])
        worker.feed(_silence(1))
        self.assertTrue(_pump(lambda: len(self.phrases) == 1))
        self.assertEqual(partials, ["phrase 1", "phrase 2"])
        self.assertEqual(self.phrases[0][0], "phrase 3")

    def test_language_of_the_phrase_travels_with_it(self):
        recognizer = _FakeRecognizer()
        recognizer.last_language = "de"
        worker = self.start(recognizer)
        worker.feed(np.concatenate([_silence(0.5), _speech(1), _silence(1)]))
        self.assertTrue(_pump(lambda: len(self.phrases) == 1))
        self.assertEqual(self.languages, ["de"])

    def test_no_interim_text_by_default(self):
        recognizer = _FakeRecognizer()
        worker = self.start(recognizer)
        partials = []
        worker.partial_recognized.connect(lambda text, lang: partials.append(text))
        worker.feed(np.concatenate([_silence(0.5), _speech(3), _silence(1)]))
        self.assertTrue(_pump(lambda: len(self.phrases) == 1))
        self.assertEqual((partials, recognizer.calls), ([], 1))

    def test_stop_recognises_the_phrase_in_progress(self):
        worker = self.start(_FakeRecognizer())
        worker.feed(np.concatenate([_silence(0.5), _speech(1)]))  # no closing pause
        worker.stop()
        self.assertTrue(_pump(lambda: len(self.phrases) == 1))
        self.assertTrue(worker.wait(5000))

    def test_missing_model_is_reported_and_the_thread_ends(self):
        worker = self.start(_FakeRecognizer(load_error=SttModelUnavailable("no model")))
        self.assertTrue(_pump(lambda: self.failed == ["no model"]))
        self.assertTrue(worker.wait(5000))
        self.assertEqual(self.ready, [])

    def test_one_failed_phrase_does_not_stop_the_worker(self):
        worker = self.start(_FakeRecognizer(fail_on={1}))
        worker.feed(np.concatenate([_speech(1), _silence(1), _speech(1), _silence(1)]))
        self.assertTrue(_pump(lambda: len(self.phrases) == 1))
        self.assertEqual(self.phrases[0][0], "phrase 2")

    def test_empty_text_is_not_emitted(self):
        recognizer = _FakeRecognizer()
        recognizer.transcribe = lambda audio: ""
        worker = self.start(recognizer)
        worker.feed(np.concatenate([_speech(1), _silence(1)]))
        worker.stop()
        self.assertTrue(worker.wait(5000))
        QApplication.processEvents()
        self.assertEqual(self.phrases, [])

    def test_phrases_too_far_behind_are_dropped(self):
        recognizer = _FakeRecognizer()
        recognizer.gate = threading.Event()
        worker = self.start(recognizer, max_lag_s=2.0)
        phrase = np.concatenate([_speech(1), _silence(1)])
        worker.feed(phrase)  # recognition of this one blocks on the gate
        self.assertTrue(_pump(lambda: recognizer.calls == 1))
        worker.feed(phrase)  # closed at ~3.4 s of the stream ...
        worker.feed(_silence(10))  # ... and 10 s more arrive before its turn comes
        worker.feed(phrase)  # fresh: nothing arrives after it
        recognizer.gate.set()
        self.assertTrue(_pump(lambda: len(self.phrases) == 2))
        self.assertEqual(worker.dropped_phrases, 1)
        self.assertEqual([p[0] for p in self.phrases], ["phrase 1", "phrase 2"])
        self.assertGreater(self.phrases[1][1], 13.0)  # the second result is the fresh phrase


if __name__ == "__main__":
    unittest.main()
