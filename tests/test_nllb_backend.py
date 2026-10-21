"""
tests/test_nllb_backend.py — the local NLLB backend with a stubbed model.

Covers:
  • model discovery: an explicit path is authoritative, auto-discovery prefers the
    canonical directory, incomplete directories are rejected with the missing files;
  • loading: a missing or incomplete model raises NllbModelUnavailable;
  • translation: FLORES codes and the token layout passed to CTranslate2, the cache
    namespace, the same-language fast path, unsupported languages, inference errors;
  • the module-level singleton and reset_client().
ctranslate2 and sentencepiece are replaced by fakes; the "model" is empty files.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import config
from tests.store_isolation import isolate_store
from translate import nllb_backend
from translate.nllb_backend import NllbBackend, NllbModelUnavailable, NllbTranslationError


def _make_model(path: Path, *, skip=()) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in nllb_backend._REQUIRED_FILES:
        if name not in skip:
            (path / name).write_bytes(b"")
    return path


class _FakeSentencePiece:
    def __init__(self, model_file):
        self.model_file = model_file

    def encode(self, text, out_type=str):
        return ["▁" + word for word in text.split()]

    def decode(self, pieces):
        return " ".join(p.lstrip("▁") for p in pieces)


class _FakeTranslator:
    """Upper-cases every token: easy to check, and keeps the target-language prefix."""

    def __init__(self, model_dir, device, compute_type, **kwargs):
        self.device = device
        self.batches = []
        self.error = None

    def translate_batch(self, batch, target_prefix, beam_size, max_decoding_length):
        if self.error is not None:
            raise self.error
        self.batches.append((batch, target_prefix))
        source = batch[0][1:-1]  # drop the source language code and </s>
        hypothesis = target_prefix[0] + [token.upper() for token in source] + ["</s>"]
        return [types.SimpleNamespace(hypotheses=[hypothesis])]


def _fake_modules():
    ct2 = types.ModuleType("ctranslate2")
    ct2.Translator = _FakeTranslator
    ct2.get_cuda_device_count = lambda: 0
    spm = types.ModuleType("sentencepiece")
    spm.SentencePieceProcessor = _FakeSentencePiece
    return {"ctranslate2": ct2, "sentencepiece": spm}


def _config(name, value):
    return mock.patch.object(type(config), name, new_callable=mock.PropertyMock, return_value=value)


class _TempDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in ("NLLB_MODEL_DIR", "NLLB_DEVICE")}
        for patcher in (
            mock.patch.dict(os.environ, env, clear=True),
            _config("NLLB_MODEL_PATH", ""),
            mock.patch.object(nllb_backend, "_models_roots", return_value=[self.root / "a", self.root / "b"]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class TestModelDiscovery(_TempDirTest):
    def test_nothing_found(self):
        self.assertIsNone(nllb_backend.resolve_model_dir())
        self.assertFalse(nllb_backend.is_available())
        self.assertIn(str(self.root / "a" / nllb_backend.MODEL_DIRNAME), nllb_backend.describe_model_location())

    def test_canonical_directory_wins_over_other_builds(self):
        _make_model(self.root / "a" / "my-finetune")
        _make_model(self.root / "b" / nllb_backend.MODEL_DIRNAME)
        canonical = _make_model(self.root / "a" / nllb_backend.MODEL_DIRNAME, skip=("model.bin",))
        # An incomplete canonical directory is skipped, not reported as the model.
        self.assertEqual(nllb_backend.resolve_model_dir(), self.root / "a" / "my-finetune")
        (canonical / "model.bin").write_bytes(b"")
        self.assertEqual(nllb_backend.resolve_model_dir(), canonical)

    def test_newest_build_first(self):
        old = _make_model(self.root / "a" / "old")
        new = _make_model(self.root / "a" / "new")
        os.utime(old / "model.bin", (1_000_000, 1_000_000))
        self.assertEqual(nllb_backend.resolve_model_dir(), new)

    def test_explicit_path_is_authoritative(self):
        _make_model(self.root / "a" / nllb_backend.MODEL_DIRNAME)
        explicit = _make_model(self.root / "custom", skip=("config.json",))
        with _config("NLLB_MODEL_PATH", str(explicit)):
            self.assertIsNone(nllb_backend.resolve_model_dir(), "no silent fallback to auto-discovery")
            self.assertIn("config.json", nllb_backend.describe_model_location())
            (explicit / "config.json").write_bytes(b"")
            self.assertEqual(nllb_backend.resolve_model_dir(), explicit)
            self.assertIn(str(explicit), nllb_backend.describe_model_location())

    def test_env_path_and_missing_directory(self):
        missing = self.root / "nowhere"
        with mock.patch.dict(os.environ, {"NLLB_MODEL_DIR": str(missing)}):
            self.assertEqual(nllb_backend.explicit_model_dir(), missing)
            self.assertIn(str(missing), nllb_backend.describe_model_location())

    def test_missing_files(self):
        path = _make_model(self.root / "m", skip=("model.bin", "sentencepiece.bpe.model"))
        self.assertEqual(nllb_backend.missing_files(path), ["model.bin", "sentencepiece.bpe.model"])


class TestLoading(_TempDirTest):
    def test_no_model_raises_unavailable(self):
        with self.assertRaises(NllbModelUnavailable):
            NllbBackend(device="cpu").ensure_loaded()

    def test_incomplete_explicit_dir_names_the_missing_files(self):
        path = _make_model(self.root / "m", skip=("shared_vocabulary.json",))
        with self.assertRaises(NllbModelUnavailable) as ctx:
            NllbBackend(path, device="cpu").ensure_loaded()
        self.assertIn("shared_vocabulary.json", str(ctx.exception))

    def test_missing_packages_raise_unavailable(self):
        path = _make_model(self.root / "m")
        with mock.patch.dict(sys.modules, {"ctranslate2": None}), self.assertRaises(NllbModelUnavailable):
            NllbBackend(path, device="cpu").ensure_loaded()

    def test_load_and_unload(self):
        path = _make_model(self.root / "m")
        backend = NllbBackend(path, device="cpu")
        with mock.patch.dict(sys.modules, _fake_modules()):
            backend.ensure_loaded()
            backend.ensure_loaded()  # second call is a no-op
        self.assertTrue(backend.is_loaded)
        self.assertEqual((backend.model_dir, backend.active_device), (path, "cpu"))
        backend.unload()
        self.assertFalse(backend.is_loaded)
        self.assertEqual(backend.active_device, "")

    def test_auto_device_without_gpu_runs_on_cpu(self):
        path = _make_model(self.root / "m")
        backend = NllbBackend(path, device="auto")
        with mock.patch.dict(sys.modules, _fake_modules()):
            backend.ensure_loaded()
        self.assertEqual(backend.active_device, "cpu")
        self.assertEqual(backend.take_notice(), "", "no GPU in auto mode is not worth a notice")


class TestTranslate(_TempDirTest):
    def setUp(self):
        super().setUp()
        isolate_store(self)
        self.backend = NllbBackend(_make_model(self.root / "m"), device="cpu")
        for patcher in (
            mock.patch.dict(sys.modules, _fake_modules()),
            mock.patch("translate.lang_detect.is_same_language", return_value=(False, "")),
            _config("NLLB_GLOSSARY", False),
            _config("TARGET_LANG", "ru"),
            _config("SOURCE_LANG", "en"),
            _config("ACTIVE_DOMAIN", "general"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_translation_uses_flores_codes(self):
        chunks = []
        self.assertEqual(self.backend.translate("  good game  ", on_chunk=chunks.append), "GOOD GAME")
        batch, prefix = self.backend._translator.batches[0]
        self.assertEqual(batch, [["eng_Latn", "▁good", "▁game", "</s>"]])
        self.assertEqual(prefix, [["rus_Cyrl"]])
        self.assertEqual(chunks, ["GOOD GAME"])

    def test_second_call_is_served_from_the_cache(self):
        self.backend.translate("good game")
        self.backend.translate("good game")
        self.assertEqual(len(self.backend._translator.batches), 1)

    def test_cache_namespace_follows_the_glossary_setting(self):
        self.assertEqual(NllbBackend._cache_domain("games"), "games|nllb")
        with _config("NLLB_GLOSSARY", True):
            self.assertRegex(NllbBackend._cache_domain("games"), r"^games\|glossary\w+\|nllb$")

    def test_empty_text(self):
        self.assertEqual(self.backend.translate("   "), "")
        self.assertEqual(self.backend.detect_and_translate(""), ("en", ""))
        self.assertFalse(self.backend.is_loaded, "nothing to translate, nothing to load")

    def test_same_language_fast_path_skips_the_model(self):
        with mock.patch("translate.lang_detect.is_same_language", return_value=(True, "ru")):
            self.assertEqual(self.backend.translate("привет"), "привет")
            self.assertEqual(self.backend.detect_and_translate("привет"), ("ru", "привет"))
        self.assertFalse(self.backend.is_loaded)

    def test_unsupported_language(self):
        with self.assertRaises(NllbTranslationError):
            self.backend.translate("hello", target_lang="xx")

    def test_inference_failure_is_a_translation_error(self):
        self.backend.ensure_loaded()
        self.backend._translator.error = RuntimeError("out of memory")
        with self.assertRaises(NllbTranslationError) as ctx:
            self.backend.translate("hello")
        self.assertIn("out of memory", str(ctx.exception))

    def test_auto_source_is_detected(self):
        with mock.patch.object(self.backend, "_detect_source", return_value="de"):
            self.assertEqual(self.backend.translate("guten tag", source_lang="auto"), "GUTEN TAG")
            self.assertEqual(self.backend.detect_and_translate("hallo welt"), ("de", "HALLO WELT"))
        self.assertEqual([b[0][0][0] for b in self.backend._translator.batches], ["deu_Latn", "deu_Latn"])

    def test_detection_falls_back_to_a_non_target_language(self):
        with mock.patch("translate.lang_detect.get_detector", side_effect=RuntimeError("no langid")):
            self.assertEqual(self.backend._detect_source("???", "ru"), "en")
            self.assertEqual(self.backend._detect_source("???", "en"), "ru")


class TestSingleton(unittest.TestCase):
    def tearDown(self):
        nllb_backend.reset_client()

    def test_get_backend_is_shared_until_reset(self):
        first = nllb_backend.get_backend()
        self.assertIs(nllb_backend.get_backend(), first)
        nllb_backend.reset_client()
        self.assertIsNot(nllb_backend.get_backend(), first)

    def test_module_functions_delegate_and_reraise(self):
        fake = mock.Mock()
        fake.translate.return_value = "x"
        fake.detect_and_translate.side_effect = NllbTranslationError("boom")
        with mock.patch.object(nllb_backend, "get_backend", return_value=fake):
            self.assertEqual(nllb_backend.translate("hi", target_lang="de"), "x")
            with self.assertRaises(NllbTranslationError):
                nllb_backend.detect_and_translate("hi")
        self.assertEqual(fake.translate.call_args.kwargs["target_lang"], "de")


if __name__ == "__main__":
    unittest.main()
