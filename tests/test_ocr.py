"""
tests/test_ocr.py — unit tests for the RapidOCR integration.

Covers:
  • Preprocessing pipeline (upscaling, RGB array format).
  • Bounding box line-sorting algorithm.
  • GPU resolution logic ("auto", "true", "false") and the DirectML mode setting.
  • Recognition-model language choice.
  • Confidence-based filtering and the GPU → CPU fallback via a mocked engine.
  • Seeding the user model dir from the models shipped with rapidocr.

No GPU, network or real model is needed: the RapidOCR engine is a mock.
"""

import importlib.util
import sys
import os
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from ocr import engine
from ocr.engine import preprocess, _sort_text_results, _resolve_gpu, recognise


def _engine_output(items):
    """Build a RapidOCROutput-like object from [(bbox, text, score), …]."""
    if not items:
        return SimpleNamespace(boxes=None, txts=None, scores=None)
    return SimpleNamespace(
        boxes=np.array([bbox for bbox, _, _ in items], dtype=np.float32),
        txts=tuple(text for _, text, _ in items),
        scores=tuple(score for _, _, score in items),
    )


def _mock_engine(items):
    return MagicMock(return_value=_engine_output(items))


class TestOCRPreprocessing(unittest.TestCase):
    """Test image preprocessing for OCR.

    preprocess() pads every side by max(8, min(24, 10 % of the short side)) so edge
    glyphs are not clipped, then upscales small crops when scale == 1
    (x3 below 100 px high, x2 below 250 px high or 500 px wide).
    """

    def test_preprocess_returns_numpy_array(self):
        img = Image.new("RGB", (100, 50), color="white")
        processed = preprocess(img, scale=2)
        self.assertIsInstance(processed, np.ndarray)
        # 8 px padding → 116×66, then the explicit 2x scale.
        self.assertEqual(processed.shape, (132, 232, 3))

    def test_preprocess_pads_and_upscales_small_crop(self):
        img = Image.new("RGB", (80, 40), color="red")
        processed = preprocess(img, scale=1)
        self.assertIsInstance(processed, np.ndarray)
        # 8 px padding → 96×56; under 100 px high → auto 3x.
        self.assertEqual(processed.shape, (168, 288, 3))

    def test_preprocess_large_crop_is_only_padded(self):
        img = Image.new("RGB", (600, 300), color="white")
        processed = preprocess(img, scale=1)
        # 24 px padding (10 % capped at 24) → 648×348; big enough, no upscale.
        self.assertEqual(processed.shape, (348, 648, 3))

    def test_preprocess_converts_grayscale_to_rgb(self):
        img = Image.new("L", (80, 40), color=128)
        processed = preprocess(img, scale=1)
        self.assertIsInstance(processed, np.ndarray)
        self.assertEqual(processed.ndim, 3)
        self.assertEqual(processed.shape[2], 3)


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


class TestGPUMode(unittest.TestCase):
    """Test the OCR_GPU_MODE setting → DirectML decision."""

    def _decide(self, mode, dml=True, legacy="auto"):
        with patch.object(type(config), "EASYOCR_GPU", legacy), \
             patch.object(type(config), "OCR_GPU_MODE", mode), \
             patch("ocr.engine._dml_available", return_value=dml):
            return engine._should_use_gpu()

    def test_auto_uses_directml_when_available(self):
        self.assertTrue(self._decide("auto"))
        self.assertFalse(self._decide("auto", dml=False))

    def test_legacy_gpu_value_behaves_like_auto(self):
        self.assertTrue(self._decide("gpu"))
        self.assertFalse(self._decide("gpu", dml=False))

    def test_cpu_never_uses_gpu(self):
        self.assertFalse(self._decide("cpu"))

    def test_legacy_env_override(self):
        self.assertFalse(self._decide("auto", legacy="false"))
        self.assertTrue(self._decide("cpu", legacy="true"))


@unittest.skipUnless(importlib.util.find_spec("rapidocr"), "rapidocr is not installed")
class TestRecLanguage(unittest.TestCase):
    """Test the recognition-model choice for the configured OCR languages."""

    def test_cyrillic_languages_use_eslav(self):
        from rapidocr import LangRec
        self.assertEqual(engine._rec_lang(["en", "ru"]), LangRec.ESLAV)
        self.assertEqual(engine._rec_lang(["uk"]), LangRec.ESLAV)
        self.assertEqual(engine._rec_lang([]), LangRec.ESLAV)

    def test_english_only_uses_en(self):
        from rapidocr import LangRec
        self.assertEqual(engine._rec_lang(["en"]), LangRec.EN)


class TestModelDir(unittest.TestCase):
    """Test seeding <user data dir>/ocr_models from the rapidocr package."""

    def test_copies_only_known_missing_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "rapidocr"
            (pkg / "models").mkdir(parents=True)
            (pkg / "models" / "PP-OCRv6_det_small.onnx").write_bytes(b"det")
            (pkg / "models" / "PP-OCRv6_rec_small.onnx").write_bytes(b"unused")
            user = Path(tmp) / "user"
            (user / "ocr_models").mkdir(parents=True)
            (user / "ocr_models" / "eslav_PP-OCRv5_rec_mobile.onnx").write_bytes(b"kept")

            fake = types.ModuleType("rapidocr")
            fake.__file__ = str(pkg / "__init__.py")
            with patch.dict(sys.modules, {"rapidocr": fake}), \
                 patch.object(type(config), "USER_DATA_DIR", user):
                model_dir = engine._model_dir()

            self.assertEqual(model_dir, user / "ocr_models")
            self.assertEqual(
                sorted(p.name for p in model_dir.iterdir()),
                ["PP-OCRv6_det_small.onnx", "eslav_PP-OCRv5_rec_mobile.onnx"],
            )
            self.assertEqual((model_dir / "eslav_PP-OCRv5_rec_mobile.onnx").read_bytes(), b"kept")


class TestRecogniseMocked(unittest.TestCase):
    """Test recognise() with a mocked RapidOCR engine."""

    @patch("ocr.engine.get_reader")
    def test_recognise_filters_low_confidence(self, mock_get_reader):
        mock_get_reader.return_value = _mock_engine([
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "Надёжный текст", 0.85),
            ([[10, 30], [100, 30], [100, 45], [10, 45]], "Мусорный шум", 0.10),
        ])

        img = Image.new("RGB", (100, 100))
        text = recognise(img)
        self.assertEqual(text, "Надёжный текст")

    @patch("ocr.engine.get_reader")
    def test_recognise_returns_empty_when_all_low_confidence(self, mock_get_reader):
        mock_get_reader.return_value = _mock_engine([
            ([[10, 10], [100, 10], [100, 25], [10, 25]], "noise", 0.05),
        ])

        img = Image.new("RGB", (100, 100))
        text = recognise(img)
        self.assertEqual(text, "")

    @patch("ocr.engine.get_reader")
    def test_recognise_handles_no_detections(self, mock_get_reader):
        mock_get_reader.return_value = _mock_engine([])
        self.assertEqual(recognise(Image.new("RGB", (100, 100))), "")

    @patch("ocr.engine.get_reader")
    def test_strip_mode_offsets_boxes(self, mock_get_reader):
        # Each strip reports one line at y=10; strips start at y=0 and y=300.
        mock_get_reader.return_value = MagicMock(side_effect=[
            _engine_output([([[10, 10], [90, 10], [90, 25], [10, 25]], "верх", 0.9)]),
            _engine_output([([[10, 10], [90, 10], [90, 25], [10, 25]], "низ", 0.9)]),
        ])
        img = Image.new("RGB", (200, 600), "white")
        # Give both strips some contrast so neither is skipped as blank.
        img.paste((0, 0, 0), (0, 0, 50, 50))
        img.paste((0, 0, 0), (0, 300, 50, 350))
        self.assertEqual(recognise(img), "верх\nниз")


class TestOnnxruntimeImport(unittest.TestCase):
    """A failed onnxruntime import is remembered and never retried."""

    def tearDown(self):
        engine._ort_import_error = None

    def test_failed_import_is_not_retried(self):
        with patch.dict(sys.modules, {"onnxruntime": None}):  # import → ImportError
            with self.assertRaises(ImportError):
                engine._onnxruntime()
        # Even with a working module now available, the failure sticks.
        with patch.dict(sys.modules, {"onnxruntime": MagicMock()}):
            with self.assertRaises(ImportError):
                engine._onnxruntime()
            self.assertFalse(engine._dml_available())

    def test_build_engine_fails_cleanly(self):
        engine._ort_import_error = OSError("DLL initialization routine failed")
        with self.assertRaises(ImportError):
            engine._build_engine(use_gpu=True)


class TestGpuFallback(unittest.TestCase):
    """A DirectML failure rebuilds the engine on the CPU and re-runs the frame."""

    def setUp(self):
        self._saved = (engine._reader, engine._reader_on_gpu)

    def tearDown(self):
        engine._reader, engine._reader_on_gpu = self._saved

    def test_gpu_error_falls_back_to_cpu(self):
        gpu = MagicMock(side_effect=RuntimeError("DirectML device removed"))
        cpu = _mock_engine([([[10, 10], [100, 10], [100, 25], [10, 25]], "текст", 0.9)])
        engine._reader, engine._reader_on_gpu = gpu, True

        with patch("ocr.engine._build_engine", return_value=cpu) as build:
            text = recognise(Image.new("RGB", (100, 100)))

        build.assert_called_once_with(use_gpu=False)
        self.assertEqual(text, "текст")
        self.assertIs(engine._reader, cpu)
        self.assertFalse(engine._reader_on_gpu)

    def test_cpu_error_is_raised(self):
        engine._reader = MagicMock(side_effect=RuntimeError("bad input"))
        engine._reader_on_gpu = False
        with patch("ocr.engine._build_engine") as build:
            with self.assertRaises(RuntimeError):
                recognise(Image.new("RGB", (100, 100)))
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
