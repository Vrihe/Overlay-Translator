"""
tests/test_ocr.py — unit tests for EasyOCR integration.

Covers:
  • Preprocessing pipeline (upscaling, RGB array format).
  • Bounding box line-sorting algorithm.
  • GPU resolution logic ("auto", "true", "false").
  • Confidence-based filtering via mocked Reader.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from ocr.engine import preprocess, _sort_text_results, _resolve_gpu, recognise


class TestOCRPreprocessing(unittest.TestCase):
    """Test image preprocessing for EasyOCR."""

    def test_preprocess_returns_numpy_array(self):
        img = Image.new("RGB", (100, 50), color="white")
        processed = preprocess(img, scale=2)
        self.assertIsInstance(processed, np.ndarray)
        self.assertEqual(processed.shape, (100, 200, 3))  # 2x height, 2x width, 3 channels

    def test_preprocess_no_scaling(self):
        img = Image.new("RGB", (80, 40), color="red")
        processed = preprocess(img, scale=1)
        self.assertIsInstance(processed, np.ndarray)
        self.assertEqual(processed.shape, (40, 80, 3))

    def test_preprocess_converts_grayscale_to_rgb(self):
        img = Image.new("L", (80, 40), color=128)
        processed = preprocess(img, scale=1)
        self.assertIsInstance(processed, np.ndarray)
        self.assertEqual(processed.shape, (40, 80, 3))


class TestBoundingBoxSorting(unittest.TestCase):
    """Test text line sorting and grouping."""

    def test_sort_lines_top_to_bottom(self):
        # Line 1: y=10, Line 2: y=40
        raw_results = [
            ([[10, 40], [100, 40], [100, 55], [10, 55]], "Вторая строка", 0.95),
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "Первая строка", 0.98),
        ]
        result_text = _sort_text_results(raw_results)
        lines = result_text.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "Первая строка")
        self.assertEqual(lines[1], "Вторая строка")

    def test_sort_same_line_left_to_right(self):
        # Two words on the same line (y=10)
        raw_results = [
            ([[120, 10], [200, 10], [200, 25], [120, 25]], "мир!", 0.9),
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "Привет", 0.95),
        ]
        result_text = _sort_text_results(raw_results)
        self.assertEqual(result_text, "Привет мир!")

    def test_empty_results(self):
        self.assertEqual(_sort_text_results([]), "")


class TestGPUResolution(unittest.TestCase):
    """Test GPU option resolving."""

    def test_explicit_boolean(self):
        self.assertTrue(_resolve_gpu(True))
        self.assertFalse(_resolve_gpu(False))

    def test_string_modes(self):
        self.assertTrue(_resolve_gpu("true"))
        self.assertTrue(_resolve_gpu("1"))
        self.assertFalse(_resolve_gpu("false"))
        self.assertFalse(_resolve_gpu("0"))


class TestRecogniseMocked(unittest.TestCase):
    """Test recognise() with a mocked Reader."""

    @patch("ocr.engine.get_reader")
    def test_recognise_filters_low_confidence(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "Надёжный текст", 0.85),
            ([[10, 30], [100, 30], [100, 45], [10, 45]], "Мусорный шум", 0.10),
        ]
        mock_get_reader.return_value = mock_reader

        img = Image.new("RGB", (100, 100))
        text = recognise(img)
        self.assertEqual(text, "Надёжный текст")

    @patch("ocr.engine.get_reader")
    def test_recognise_returns_empty_when_all_low_confidence(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "noise", 0.05),
        ]
        mock_get_reader.return_value = mock_reader

        img = Image.new("RGB", (100, 100))
        text = recognise(img)
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
