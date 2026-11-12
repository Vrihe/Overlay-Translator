"""
tests/test_audio_phrase_translator.py — audio/phrase_translator.py.

Sentence splitting, the per-backend translation of one phrase (``translate.backend``
mocked: no network, no model) and the PhraseTranslator thread.
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audio import phrase_translator
from audio.phrase_translator import PhraseTranslator, split_sentences, translate_phrase
from cache import store
from settings import config_manager
from tests.store_isolation import isolate_store

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def _pump(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    return condition()


class TestSplitSentences(unittest.TestCase):
    def test_splits_on_sentence_ends(self):
        self.assertEqual(
            split_sentences("We go left. Watch the boss! Are you ready? Go."),
            ["We go left.", "Watch the boss!", "Are you ready?", "Go."],
        )

    def test_one_sentence_stays_whole(self):
        self.assertEqual(split_sentences("  just one sentence without an end  "), ["just one sentence without an end"])

    def test_numbers_and_lowercase_do_not_split(self):
        self.assertEqual(split_sentences("It costs 3.5 gold. ok then"), ["It costs 3.5 gold. ok then"])

    def test_abbreviations_do_not_split(self):
        self.assertEqual(split_sentences("Ask Dr. Smith about it. He knows."), ["Ask Dr. Smith about it.", "He knows."])

    def test_empty(self):
        self.assertEqual(split_sentences("   "), [])


class _BackendCase(unittest.TestCase):
    backend_id = "nllb"
    target = "ru"

    def setUp(self):
        isolate_store(self)
        config_manager._cache = {**config_manager.DEFAULTS, "target_language": self.target, "active_domain": "games"}
        self.addCleanup(setattr, config_manager, "_cache", None)
        self.calls = []

        def fake_translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None):
            self.calls.append((text, source_lang, domain_id))
            store.save_to_cache(text, source_lang, "ru", f"<{text}>")  # what the real backends do
            return f"<{text}>"

        for patcher in (
            mock.patch("translate.backend.get_active_backend", return_value=self.backend_id),
            mock.patch("translate.backend.translate", side_effect=fake_translate),
            mock.patch("translate.backend.take_notice", side_effect=["", "model on CPU", ""]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class TestTranslatePhraseNllb(_BackendCase):
    def test_translated_sentence_by_sentence(self):
        text, notice = translate_phrase("We go left. Watch the boss!")
        self.assertEqual(text, "<We go left.> <Watch the boss!>")
        self.assertEqual(self.calls, [("We go left.", "en", "games"), ("Watch the boss!", "en", "games")])
        self.assertEqual(notice, "model on CPU")

    def test_nothing_reaches_the_history(self):
        translate_phrase("We go left.")
        self.assertEqual(store.get_all_history(), [])
        # ... while a translation made outside subtitles on the same thread still does.
        store.save_to_cache("hello", "en", "ru", "привет")
        self.assertEqual(len(store.get_all_history()), 1)


class TestTranslatePhraseCloud(_BackendCase):
    backend_id = "google"

    def test_whole_phrase_in_one_request(self):
        text, _notice = translate_phrase("We go left. Watch the boss!")
        self.assertEqual(text, "<We go left. Watch the boss!>")
        self.assertEqual(len(self.calls), 1)


class TestTranslatePhraseOtherLanguage(_BackendCase):
    def test_source_language_reaches_the_backend(self):
        translate_phrase("Wir gehen links.", "de")
        self.assertEqual({call[1] for call in self.calls}, {"de"})

    def test_speech_already_in_the_target_language_is_shown_as_is(self):
        self.assertEqual(translate_phrase("Идём налево.", "ru"), ("Идём налево.", ""))
        self.assertEqual(self.calls, [])


class TestTranslatePhraseSameLanguage(_BackendCase):
    target = "en"

    def test_english_target_shows_the_speech_as_is(self):
        self.assertEqual(translate_phrase("We go left."), ("We go left.", ""))
        self.assertEqual(self.calls, [])


class TestPhraseTranslator(unittest.TestCase):
    def start(self, translate, **kwargs):
        worker = PhraseTranslator(translate, **kwargs)
        self.done, self.failed = [], []
        worker.translated.connect(lambda source, text, notice: self.done.append((source, text, notice)))
        worker.failed.connect(lambda source, message: self.failed.append((source, message)))
        worker.start()
        self.addCleanup(self.finish, worker)
        return worker

    def finish(self, worker):
        worker.stop()
        self.assertTrue(worker.wait(5000))

    def test_phrases_are_translated_in_order_off_the_caller_thread(self):
        threads = set()

        def translate(text):
            threads.add(threading.get_ident())
            return text.upper(), "note" if text == "b" else ""

        worker = self.start(translate)
        for text in ("a", "b", "c"):
            worker.submit(text)
        self.assertTrue(_pump(lambda: len(self.done) == 3))
        self.assertEqual(self.done, [("a", "A", ""), ("b", "B", "note"), ("c", "C", "")])
        self.assertNotIn(threading.get_ident(), threads)

    def test_interim_text_is_translated_and_a_waiting_phrase_goes_first(self):
        gate = threading.Event()
        order = []

        def translate(text):
            if text == "first":
                gate.wait(5)
            order.append(text)
            return text.upper(), ""

        worker = self.start(translate)
        partials = []
        worker.partial_translated.connect(lambda source, text: partials.append((source, text)))
        worker.submit("first")
        worker.submit_partial("old interim")
        worker.submit_partial("new interim")  # replaces the older one
        gate.set()
        self.assertTrue(_pump(lambda: partials == [("new interim", "NEW INTERIM")]))
        self.assertEqual(order, ["first", "new interim"])
        worker.submit_partial("stale")
        worker.submit("second")  # the phrase supersedes its interim text
        self.assertTrue(_pump(lambda: len(self.done) == 2))
        self.assertNotIn(("stale", "STALE"), partials)

    def test_recognised_language_is_passed_to_the_translation(self):
        calls = []

        def translate(text, lang="none given"):
            calls.append((text, lang))
            return text.upper(), ""

        worker = self.start(translate)
        worker.submit("hallo", "de")
        worker.submit("hello")
        self.assertTrue(_pump(lambda: len(self.done) == 2))
        self.assertEqual(calls, [("hallo", "de"), ("hello", "none given")])

    def test_a_failed_interim_translation_is_silent(self):
        def translate(text):
            raise RuntimeError("no network")

        worker = self.start(translate)
        partials = []
        worker.partial_translated.connect(lambda source, text: partials.append(text))
        worker.submit_partial("interim")
        worker.submit("phrase")
        self.assertTrue(_pump(lambda: len(self.failed) == 1))
        self.assertEqual((partials, self.failed[0][0]), ([], "phrase"))

    def test_a_failed_phrase_is_reported_and_the_next_one_still_runs(self):
        def translate(text):
            if text == "bad":
                raise RuntimeError("quota exceeded")
            return text.upper(), ""

        worker = self.start(translate)
        worker.submit("bad")
        worker.submit("good")
        self.assertTrue(_pump(lambda: len(self.done) == 1 and len(self.failed) == 1))
        self.assertEqual(self.failed, [("bad", "quota exceeded")])
        self.assertEqual(self.done, [("good", "GOOD", "")])

    def test_backlog_drops_the_oldest_phrases(self):
        gate = threading.Event()
        started = threading.Event()

        def translate(text):
            started.set()
            gate.wait(5)
            return text.upper(), ""

        worker = self.start(translate, max_pending=2)
        self.addCleanup(gate.set)
        worker.submit("first")
        self.assertTrue(started.wait(5))  # "first" is being translated: the rest queue up
        for text in ("b", "c", "d", "e"):
            worker.submit(text)
        gate.set()
        self.assertTrue(_pump(lambda: len(self.done) == 3))
        self.assertEqual([d[0] for d in self.done], ["first", "d", "e"])
        self.assertEqual(worker.dropped_phrases, 2)

    def test_empty_translation_is_not_emitted(self):
        worker = self.start(lambda text: ("", "") if text == "skip" else (text, ""))
        worker.submit("skip")
        worker.submit("shown")
        self.assertTrue(_pump(lambda: len(self.done) == 1))
        self.assertEqual(self.done[0][0], "shown")

    def test_stop_drops_waiting_phrases(self):
        gate = threading.Event()
        started = threading.Event()

        def translate(text):
            started.set()
            gate.wait(5)
            return text, ""

        worker = self.start(translate)
        worker.submit("running")
        self.assertTrue(started.wait(5))
        worker.submit("waiting")
        worker.stop()
        gate.set()
        self.assertTrue(worker.wait(5000))
        _pump(lambda: False, timeout=0.05)
        self.assertEqual([d[0] for d in self.done], ["running"])

    def test_default_translate_function(self):
        self.assertIs(PhraseTranslator()._translate, phrase_translator.translate_phrase)


if __name__ == "__main__":
    unittest.main()
