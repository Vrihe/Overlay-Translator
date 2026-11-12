"""
tests/test_audio_stt.py — audio/stt.py with fake ``faster_whisper`` / ``ctranslate2``.

Covers model discovery (never downloads), the fixed decoding parameters, and the CPU
fallback for every CUDA failure mode. No real model, GPU or network is needed.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import translate.cuda_download  # noqa: F401  (patched by name below)
import translate.cuda_support  # noqa: F401
from audio import stt


def _make_model(root: Path, name: str = stt.DEFAULT_MODEL, skip: str = "") -> Path:
    path = root / "models" / stt.model_dirname(name)
    path.mkdir(parents=True)
    for filename in ("model.bin", "config.json", "tokenizer.json"):
        if filename != skip:
            (path / filename).write_bytes(b"")
    return path


class _Segment:
    def __init__(self, text):
        self.text = text


class _FakeWhisperModel:
    created = []
    fail_on_cuda = None  # exception raised by a CUDA model on its first transcribe

    def __init__(self, path, **kwargs):
        self.path = path
        self.kwargs = kwargs
        self.calls = []
        _FakeWhisperModel.created.append(self)

    #: What detect_language() reports: (language, probability) or an exception.
    detected = ("en", 0.99)

    def detect_language(self, audio):
        if isinstance(_FakeWhisperModel.detected, Exception):
            raise _FakeWhisperModel.detected
        language, probability = _FakeWhisperModel.detected
        return language, probability, [(language, probability)]

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if self.kwargs["device"] == "cuda" and _FakeWhisperModel.fail_on_cuda:
            raise _FakeWhisperModel.fail_on_cuda
        return iter([_Segment(" Hello "), _Segment("world. ")]), types.SimpleNamespace(language="de")


class _SttCase(unittest.TestCase):
    gpu_count = 0

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _FakeWhisperModel.created = []
        _FakeWhisperModel.fail_on_cuda = None
        _FakeWhisperModel.detected = ("en", 0.99)
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = _FakeWhisperModel
        fake_ct2 = types.ModuleType("ctranslate2")
        fake_ct2.get_cuda_device_count = lambda: self.gpu_count
        self._patches = [
            patch.dict(sys.modules, {"faster_whisper": fake_fw, "ctranslate2": fake_ct2}),
            patch.object(
                stt,
                "model_dirs",
                lambda name=stt.DEFAULT_MODEL: [
                    self.root / "models" / stt.model_dirname(name),
                    self.root / "user" / "models" / stt.model_dirname(name),
                ],
            ),
            patch.object(stt.os, "name", "nt"),
            patch("translate.cuda_support.prepare_cuda_libraries", return_value=self.root / "cublas"),
            patch.object(stt, "prepare_cudnn", return_value=self.root / "cudnn"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class TestModelDiscovery(_SttCase):
    def test_missing_model_is_an_explicit_error(self):
        recognizer = stt.SpeechRecognizer()
        with self.assertRaises(stt.SttModelUnavailable) as ctx:
            recognizer.ensure_loaded()
        self.assertIn(stt.DEFAULT_MODEL, str(ctx.exception))
        self.assertEqual(_FakeWhisperModel.created, [])  # nothing loaded, nothing downloaded

    def test_incomplete_model_is_skipped(self):
        _make_model(self.root, skip="tokenizer.json")
        self.assertIsNone(stt.resolve_model_dir())

    def test_explicit_incomplete_dir_names_the_missing_file(self):
        path = _make_model(self.root, skip="model.bin")
        with self.assertRaises(stt.SttModelUnavailable) as ctx:
            stt.SpeechRecognizer(model_dir=path).ensure_loaded()
        self.assertIn("model.bin", str(ctx.exception))

    def test_project_dir_wins_over_user_data(self):
        first = _make_model(self.root)
        _make_model(self.root / "user")
        self.assertEqual(stt.resolve_model_dir(), first)

    def test_missing_package_is_an_explicit_error(self):
        _make_model(self.root)
        with patch.dict(sys.modules, {"faster_whisper": None}):
            with self.assertRaises(stt.SttModelUnavailable):
                stt.SpeechRecognizer().ensure_loaded()

    def test_model_is_loaded_from_disk_only(self):
        path = _make_model(self.root)
        recognizer = stt.SpeechRecognizer(device="cpu")
        recognizer.ensure_loaded()
        model = _FakeWhisperModel.created[0]
        self.assertEqual(model.path, str(path))
        self.assertTrue(model.kwargs["local_files_only"])
        self.assertEqual((model.kwargs["device"], model.kwargs["compute_type"]), ("cpu", "int8"))
        self.assertEqual(recognizer.active_device, "cpu")


class TestTranscribe(_SttCase):
    def test_fixed_decoding_parameters_and_joined_text(self):
        _make_model(self.root)
        recognizer = stt.SpeechRecognizer(device="cpu")
        text = recognizer.transcribe(np.zeros(16000, dtype="float32"))
        self.assertEqual(text, "Hello world.")
        call = _FakeWhisperModel.created[0].calls[0]
        self.assertEqual(call["language"], "en")
        self.assertEqual(call["beam_size"], 1)
        self.assertFalse(call["condition_on_previous_text"])
        self.assertFalse(call["vad_filter"])
        self.assertTrue(call["without_timestamps"])

    def test_unload_forgets_the_model(self):
        _make_model(self.root)
        recognizer = stt.SpeechRecognizer(device="cpu")
        recognizer.ensure_loaded()
        recognizer.unload()
        self.assertFalse(recognizer.is_loaded)
        self.assertEqual(recognizer.active_device, "")


class TestLanguageFilter(_SttCase):
    """skip_foreign: a multilingual model drops phrases confidently in another language."""

    def _text(self, model="small", detected=("en", 0.99), skip_foreign=True):
        _make_model(self.root, model)
        _FakeWhisperModel.detected = detected
        self.recognizer = stt.SpeechRecognizer(model, device="cpu", skip_foreign=skip_foreign)
        return self.recognizer.transcribe(np.zeros(16000, dtype="float32"))

    def test_english_phrase_is_recognised_as_english(self):
        self.assertEqual(self._text(), "Hello world.")
        self.assertEqual(_FakeWhisperModel.created[0].calls[0]["language"], "en")
        self.assertEqual(self.recognizer.skipped_foreign, 0)

    def test_foreign_phrase_is_skipped_without_decoding(self):
        self.assertEqual(self._text(detected=("ru", 0.93)), "")
        self.assertEqual(_FakeWhisperModel.created[0].calls, [])
        self.assertEqual(self.recognizer.skipped_foreign, 1)

    def test_unclear_phrase_is_kept(self):
        self.assertEqual(self._text(detected=("de", 0.31)), "Hello world.")

    def test_failed_detection_keeps_the_phrase(self):
        self.assertEqual(self._text(detected=RuntimeError("boom")), "Hello world.")

    def test_filter_is_off_by_default(self):
        self.assertEqual(self._text(detected=("ru", 0.93), skip_foreign=False), "Hello world.")
        self.assertFalse(self.recognizer.filters_language)

    def test_english_only_model_cannot_filter(self):
        self.assertEqual(self._text(model="small.en", detected=("ru", 0.93)), "Hello world.")
        self.assertFalse(self.recognizer.filters_language)
        self.assertTrue(stt.is_multilingual("small"))
        self.assertFalse(stt.is_multilingual("base.en"))


class TestSpeechLanguage(_SttCase):
    def _recognizer(self, model="small", **kwargs):
        _make_model(self.root, model)
        recognizer = stt.SpeechRecognizer(model, device="cpu", **kwargs)
        recognizer.transcribe(np.zeros(16000, dtype="float32"))
        return recognizer, _FakeWhisperModel.created[0].calls[0]["language"]

    def test_fixed_language_is_passed_to_the_model(self):
        recognizer, passed = self._recognizer(language="ru")
        self.assertEqual((passed, recognizer.last_language), ("ru", "ru"))

    def test_auto_detects_the_language_of_each_phrase(self):
        recognizer, passed = self._recognizer(language="auto")
        self.assertIsNone(passed)
        self.assertEqual(recognizer.last_language, "de")  # what the model reported

    def test_english_only_model_always_recognises_english(self):
        recognizer, passed = self._recognizer(model="small.en", language="ru")
        self.assertEqual((passed, recognizer.last_language), ("en", "en"))

    def test_filter_follows_the_chosen_language(self):
        _make_model(self.root, "small")
        _FakeWhisperModel.detected = ("en", 0.95)
        recognizer = stt.SpeechRecognizer("small", device="cpu", language="ru", skip_foreign=True)
        self.assertEqual(recognizer.transcribe(np.zeros(16000, dtype="float32")), "")
        _FakeWhisperModel.detected = ("ru", 0.95)
        self.assertEqual(recognizer.transcribe(np.zeros(16000, dtype="float32")), "Hello world.")

    def test_filter_is_off_when_every_language_is_accepted(self):
        _make_model(self.root, "small")
        recognizer = stt.SpeechRecognizer("small", device="cpu", language="auto", skip_foreign=True)
        self.assertFalse(recognizer.filters_language)


class TestCudaFallback(_SttCase):
    def setUp(self):
        super().setUp()
        _make_model(self.root)

    def load(self, device="auto"):
        recognizer = stt.SpeechRecognizer(device=device)
        recognizer.ensure_loaded()
        return recognizer

    def test_gpu_is_used_and_warmed_up(self):
        self.gpu_count = 1
        recognizer = self.load()
        self.assertEqual(recognizer.active_device, "cuda")
        model = _FakeWhisperModel.created[0]
        self.assertEqual((model.kwargs["device"], model.kwargs["compute_type"]), ("cuda", "float16"))
        self.assertEqual(len(model.calls), 1)  # the warm-up that makes CUDA libraries load
        self.assertEqual(recognizer.take_notice(), "")

    def test_no_gpu_in_auto_mode_is_silent(self):
        recognizer = self.load()
        self.assertEqual(recognizer.active_device, "cpu")
        self.assertEqual(recognizer.take_notice(), "")

    def test_no_gpu_in_cuda_mode_leaves_a_notice(self):
        recognizer = self.load("cuda")
        self.assertEqual(recognizer.active_device, "cpu")
        self.assertIn("CPU", recognizer.take_notice())
        self.assertEqual(recognizer.take_notice(), "")  # one-shot

    def test_missing_cudnn_never_creates_a_cuda_model(self):
        # With cuDNN missing CTranslate2 aborts the process, so the GPU must not be tried.
        self.gpu_count = 1
        with patch.object(stt, "prepare_cudnn", return_value=None):
            recognizer = self.load()
        self.assertEqual(recognizer.active_device, "cpu")
        self.assertEqual([m.kwargs["device"] for m in _FakeWhisperModel.created], ["cpu"])

    def test_missing_cublas_never_creates_a_cuda_model(self):
        self.gpu_count = 1
        with patch("translate.cuda_support.prepare_cuda_libraries", return_value=None):
            recognizer = self.load()
        self.assertEqual([m.kwargs["device"] for m in _FakeWhisperModel.created], ["cpu"])
        self.assertEqual(recognizer.active_device, "cpu")

    def test_cuda_init_failure_falls_back_with_a_notice(self):
        self.gpu_count = 1
        _FakeWhisperModel.fail_on_cuda = RuntimeError("CUDA out of memory")
        recognizer = self.load()
        self.assertEqual(recognizer.active_device, "cpu")
        self.assertIn("CUDA out of memory", recognizer.take_notice())

    def test_unknown_device_means_auto(self):
        self.assertEqual(stt.SpeechRecognizer(device="tpu")._device, "auto")


class TestCudnnDiscovery(unittest.TestCase):
    def test_pip_wheel_dir_is_found_and_put_on_path_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "site-packages" / "nvidia" / "cudnn" / "bin"
            wheel.mkdir(parents=True)
            (wheel / stt.CUDNN_DLL).write_bytes(b"")
            with (
                patch.object(sys, "path", [str(root / "site-packages")]),
                patch("translate.cuda_download.cuda_dir", return_value=root / "app-cuda"),
                patch("translate.cuda_download.cudnn_dir", return_value=root / "app-cudnn"),
                patch("translate.cuda_support._toolkit_env_dirs", return_value=[]),
                patch("translate.cuda_support._toolkit_default_dirs", return_value=[]),
                patch.object(stt.os, "name", "nt"),
                patch.dict(os.environ, {"PATH": "base"}),
                patch.object(stt, "_cudnn_registered", set()),
            ):
                self.assertEqual(stt.find_cudnn_dir(), wheel)
                self.assertEqual(stt.prepare_cudnn(), wheel)
                self.assertEqual(stt.prepare_cudnn(), wheel)
                self.assertEqual(os.environ["PATH"].split(os.pathsep), [str(wheel), "base"])

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(sys, "path", [tmp]),
                patch("translate.cuda_download.cuda_dir", return_value=Path(tmp) / "app-cuda"),
                patch("translate.cuda_download.cudnn_dir", return_value=Path(tmp) / "app-cudnn"),
                patch("translate.cuda_support._toolkit_env_dirs", return_value=[]),
                patch("translate.cuda_support._toolkit_default_dirs", return_value=[]),
                patch.object(stt.os, "name", "nt"),
            ):
                self.assertIsNone(stt.prepare_cudnn())


if __name__ == "__main__":
    unittest.main()
