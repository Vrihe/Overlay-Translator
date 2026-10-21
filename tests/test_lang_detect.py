"""
tests/test_lang_detect.py — tests for language auto-detection and cache.

Covers:
  • LangidDetector correctly identifies en/ru/de/pl on reference strings.
  • Cache composite key distinguishes (text, source_lang, target_lang).
"""

import os
import sys
import unittest

# Ensure project root is on the path so bare ``import config`` works.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from translate.lang_detect import LangidDetector, get_detector

# ── LangidDetector accuracy tests ────────────────────────


class TestLangidDetector(unittest.TestCase):
    """LangidDetector must return the correct ISO 639-1 code for
    unambiguous reference strings that are longer than the detection
    threshold.
    """

    @classmethod
    def setUpClass(cls):
        cls.detector = LangidDetector()

    # Each tuple: (expected_code, sample_text)
    _SAMPLES = [
        ("en", "The quick brown fox jumps over the lazy dog"),
        ("en", "Please enter your username and password to continue"),
        ("ru", "Привет, как у тебя дела сегодня?"),
        ("ru", "Пожалуйста, введите ваши данные для входа в систему"),
        ("de", "Guten Tag, wie geht es Ihnen heute?"),
        ("de", "Ich möchte ein Stück Kuchen bestellen"),
        ("pl", "Dzień dobry, jak się masz dzisiaj?"),
        ("pl", "Proszę podać swoje imię i nazwisko"),
    ]

    def test_detects_known_languages(self):
        for expected, text in self._SAMPLES:
            with self.subTest(expected=expected, text=text[:40]):
                result = self.detector.detect(text)
                self.assertEqual(
                    result,
                    expected,
                    f"Expected '{expected}' for text '{text[:40]}…', got '{result}'",
                )


# ── Cache composite-key tests ───────────────────────────


class TestCacheCompositeKey(unittest.TestCase):
    """The cache must treat (text, source_lang_A, target) and
    (text, source_lang_B, target) as distinct entries.
    """

    def setUp(self):
        """Every cache read/write goes to a throw-away DB (never the real history)."""
        from tests.store_isolation import isolate_store

        isolate_store(self)

    def test_different_source_lang_not_cached_together(self):
        """Same text + different source_lang → different cache entries."""
        from cache import store

        text = "Hello world"

        store.save_to_cache(text, "en", "ru", "Привет мир")
        store.save_to_cache(text, "de", "ru", "Hallo Welt (de→ru)")

        result_en = store.get_cached(text, "en", "ru")
        result_de = store.get_cached(text, "de", "ru")

        self.assertEqual(result_en, "Привет мир")
        self.assertEqual(result_de, "Hallo Welt (de→ru)")
        self.assertNotEqual(result_en, result_de)

    def test_different_target_lang_not_cached_together(self):
        """Same text + same source + different target_lang → distinct."""
        from cache import store

        text = "Hello world"

        store.save_to_cache(text, "en", "ru", "Привет мир")
        store.save_to_cache(text, "en", "de", "Hallo Welt")

        result_ru = store.get_cached(text, "en", "ru")
        result_de = store.get_cached(text, "en", "de")

        self.assertEqual(result_ru, "Привет мир")
        self.assertEqual(result_de, "Hallo Welt")
        self.assertNotEqual(result_ru, result_de)


# ── Factory tests ────────────────────────────────────────


class TestGetDetector(unittest.TestCase):
    """get_detector() must return the right subclass and raise on unknown."""

    def test_langid_engine(self):
        detector = get_detector("langid")
        self.assertIsInstance(detector, LangidDetector)

    def test_unknown_engine_raises(self):
        with self.assertRaises(ValueError):
            get_detector("nonexistent_engine_xyz")


if __name__ == "__main__":
    unittest.main()
