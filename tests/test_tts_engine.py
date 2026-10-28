"""
tests/test_tts_engine.py — speech runs on one worker thread that owns the pyttsx3
engine (SAPI/COM): the engine is created once and every call comes from that thread.

pyttsx3 is a fake; nothing is spoken.
"""

import queue
import threading
import unittest
from unittest import mock

from tts import engine as tts


class _FakeEngine:
    def __init__(self, spoken: list, done: threading.Semaphore):
        self._spoken = spoken
        self._done = done
        self.threads = set()

    def say(self, text):
        self.threads.add(threading.get_ident())
        self._spoken.append(text)

    def runAndWait(self):
        self.threads.add(threading.get_ident())
        self._done.release()


class TestSpeak(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self.done = threading.Semaphore(0)
        self.fake = _FakeEngine(self.spoken, self.done)
        self.pyttsx3 = mock.Mock()
        self.pyttsx3.init.return_value = self.fake
        for patcher in (
            mock.patch.object(tts, "pyttsx3", self.pyttsx3, create=True),
            mock.patch.object(tts, "_HAS_PYTTSX3", True),
            mock.patch.object(tts, "_requests", queue.Queue()),
            mock.patch.object(tts, "_worker", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_one_engine_on_one_thread(self):
        tts.speak("first")
        self.assertTrue(self.done.acquire(timeout=5))
        tts.speak("second")
        self.assertTrue(self.done.acquire(timeout=5))

        self.assertEqual(self.spoken, ["first", "second"])
        self.pyttsx3.init.assert_called_once()
        self.assertEqual(len(self.fake.threads), 1)
        self.assertNotIn(threading.get_ident(), self.fake.threads)

    def test_blank_text_is_ignored(self):
        tts.speak("   ")
        self.assertIsNone(tts._worker)


if __name__ == "__main__":
    unittest.main()
