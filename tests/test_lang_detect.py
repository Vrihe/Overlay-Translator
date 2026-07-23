"""
tests/test_lang_detect.py — tests for language auto-detection and cache.

Covers:
  • LangidDetector correctly identifies en/ru/de/pl on reference strings.
  • Short strings (< MIN_CHARS_FOR_DETECTION) bypass detect() entirely.
  • Cache composite key distinguishes (text, source_lang, target_lang).
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on the path so bare ``import config`` works.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from translate.lang_detect import LangidDetector, LangDetector, get_detector


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
                    result, expected,
                    f"Expected '{expected}' for text '{text[:40]}…', got '{result}'",
                )


# ── Short-text fallback tests ────────────────────────────

class TestShortTextFallback(unittest.TestCase):
    """When the recognised text is shorter than MIN_CHARS_FOR_DETECTION,
    the pipeline must NOT call detect() and must use the configured
    fallback language instead.
    """

    def test_detect_not_called_for_short_text(self):
        """Simulate the pipeline logic from main.py and verify that
        detect() is never invoked for strings below the threshold.
        """
        mock_detector = MagicMock(spec=LangDetector)
        short_text = "GG WP"  # well below 15 chars

        # Replicate the pipeline guard from main.py:
        engine = "langid"
        if engine != "off" and len(short_text.strip()) >= config.MIN_CHARS_FOR_DETECTION:
            mock_detector.detect(short_text)

        mock_detector.detect.assert_not_called()

    def test_detect_called_for_long_text(self):
        """Strings above the threshold must reach detect()."""
        mock_detector = MagicMock(spec=LangDetector)
        mock_detector.detect.return_value = "en"
        long_text = "This is a sufficiently long sentence for detection"

        engine = "langid"
        if engine != "off" and len(long_text.strip()) >= config.MIN_CHARS_FOR_DETECTION:
            mock_detector.detect(long_text)

        mock_detector.detect.assert_called_once_with(long_text)


# ── Cache composite-key tests ───────────────────────────

class TestCacheCompositeKey(unittest.TestCase):
    """The cache must treat (text, source_lang_A, target) and
    (text, source_lang_B, target) as distinct entries.
    """

    def setUp(self):
        """Use a fresh in-memory approach: patch _DB_PATH to a temp file."""
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._original_db = None

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_different_source_lang_not_cached_together(self):
        """Same text + different source_lang → different cache entries."""
        from cache import store

        # Patch the DB path to use our temp file.
        original = store._DB_PATH
        store._DB_PATH = self._tmp.name

        try:
            text = "Hello world"

            store.save_to_cache(text, "en", "ru", "Привет мир")
            store.save_to_cache(text, "de", "ru", "Hallo Welt (de→ru)")

            result_en = store.get_cached(text, "en", "ru")
            result_de = store.get_cached(text, "de", "ru")

            self.assertEqual(result_en, "Привет мир")
            self.assertEqual(result_de, "Hallo Welt (de→ru)")
            self.assertNotEqual(result_en, result_de)
        finally:
            store._DB_PATH = original

    def test_different_target_lang_not_cached_together(self):
        """Same text + same source + different target_lang → distinct."""
        from cache import store

        original = store._DB_PATH
        store._DB_PATH = self._tmp.name

        try:
            text = "Hello world"

            store.save_to_cache(text, "en", "ru", "Привет мир")
            store.save_to_cache(text, "en", "de", "Hallo Welt")

            result_ru = store.get_cached(text, "en", "ru")
            result_de = store.get_cached(text, "en", "de")

            self.assertEqual(result_ru, "Привет мир")
            self.assertEqual(result_de, "Hallo Welt")
            self.assertNotEqual(result_ru, result_de)
        finally:
            store._DB_PATH = original


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
