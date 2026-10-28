"""
tests/test_backend_dispatch.py — translate.backend routes each call to the selected backend.

Covers:
  • Google / DeepL / Azure go through the NMT client, with a cache keyed per backend.
  • The local NLLB model is used when it loads; a missing model falls back to the API
    and leaves a one-shot notice, while a translation error of a loaded model propagates.
  • preload() reports the state of each backend without raising.
No network, model or GPU is needed: the clients and the NLLB backend are fakes.
"""

import unittest
from pathlib import Path
from unittest import mock

import config
from tests.store_isolation import isolate_store
from translate import backend
from translate.nllb_backend import NllbModelUnavailable, NllbTranslationError


def _config(name, value):
    return mock.patch.object(type(config), name, new_callable=mock.PropertyMock, return_value=value)


class _FakeNmtClient:
    def __init__(self, detected="en", translated="привет"):
        self.calls = []
        self._result = (detected, translated)

    def translate(self, text, target_lang, source_lang):
        self.calls.append((text, target_lang, source_lang))
        return self._result


class _FakeNllb:
    """Stands in for translate.nllb_backend.NllbBackend."""

    def __init__(self, load_error=None, notice=""):
        self._load_error = load_error
        self._notice = notice
        self.active_device = "cpu"
        self.load_seconds = 1.25
        self.model_dir = Path("models/nllb")

    def ensure_loaded(self):
        if self._load_error is not None:
            raise self._load_error

    def take_notice(self):
        notice, self._notice = self._notice, ""
        return notice


class TestNmtBackends(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        for patcher in (_config("TARGET_LANG", "ru"), _config("SOURCE_LANG", "auto")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _use(self, name, client):
        stack = [
            _config("TRANSLATION_BACKEND", name),
            mock.patch.object(backend, "_get_nmt_client", return_value=client),
        ]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def test_miss_calls_the_client_and_caches_the_result(self):
        client = _FakeNmtClient()
        self._use("deepl", client)
        chunks = []

        self.assertEqual(backend.translate("hello", on_chunk=chunks.append), "привет")
        self.assertEqual(backend.translate("hello"), "привет")

        self.assertEqual(client.calls, [("hello", "ru", None)], "the second call must be a cache hit")
        self.assertEqual(chunks, ["привет"])

    def test_source_language_from_settings_is_passed_to_the_client(self):
        client = _FakeNmtClient()
        self._use("google", client)
        with _config("SOURCE_LANG", "de"):
            backend.translate("hallo")
        self.assertEqual(client.calls, [("hallo", "ru", "de")])

    def test_cache_is_separate_per_backend(self):
        google = _FakeNmtClient(translated="от google")
        self._use("google", google)
        backend.translate("hello", source_lang="en")

        azure = _FakeNmtClient(translated="от azure")
        with (
            _config("TRANSLATION_BACKEND", "azure"),
            mock.patch.object(backend, "_get_nmt_client", return_value=azure),
        ):
            self.assertEqual(backend.translate("hello", source_lang="en"), "от azure")
        self.assertEqual(len(azure.calls), 1)

    def test_detect_and_translate_returns_the_detected_language(self):
        self._use("google", _FakeNmtClient(detected="de", translated="привет"))
        self.assertEqual(backend.detect_and_translate("hallo"), ("de", "привет"))

    def test_nmt_backends_never_touch_the_llm(self):
        self._use("azure", _FakeNmtClient())
        with mock.patch("translate.llm_client.translate", side_effect=AssertionError("LLM called")):
            backend.translate("hello")

    def test_unknown_nmt_client_is_rejected(self):
        with self.assertRaises(ValueError):
            backend._get_nmt_client("yandex")

    def test_client_modules_are_resolved_lazily(self):
        from translate import azure_client, deepl_client, google_client

        self.assertIs(backend._get_nmt_client("google"), google_client)
        self.assertIs(backend._get_nmt_client("deepl"), deepl_client)
        self.assertIs(backend._get_nmt_client("azure"), azure_client)


class TestNllbAndApiFallback(unittest.TestCase):
    def setUp(self):
        patcher = _config("TRANSLATION_BACKEND", "nllb")
        patcher.start()
        self.addCleanup(patcher.stop)
        backend.clear_notice()

    def _nllb(self, fake):
        patcher = mock.patch("translate.nllb_backend.get_backend", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_loaded_model_translates_locally(self):
        self._nllb(_FakeNllb())
        with (
            mock.patch("translate.nllb_backend.translate", return_value="локально") as local,
            mock.patch("translate.llm_client.translate", side_effect=AssertionError("API called")),
        ):
            self.assertEqual(backend.translate("hello", target_lang="ru"), "локально")
        local.assert_called_once()
        self.assertEqual(backend.take_notice(), "")

    def test_load_notice_reaches_the_ui_once(self):
        self._nllb(_FakeNllb(notice="CUDA unavailable, using CPU inference"))
        with mock.patch("translate.nllb_backend.detect_and_translate", return_value=("en", "локально")):
            self.assertEqual(backend.detect_and_translate("hello"), ("en", "локально"))
        self.assertIn("CUDA unavailable", backend.take_notice())
        self.assertEqual(backend.take_notice(), "")

    def test_missing_model_falls_back_to_the_api_with_a_notice(self):
        self._nllb(_FakeNllb(load_error=NllbModelUnavailable("model.bin missing\nmore details")))
        with mock.patch("translate.llm_client.translate", return_value="через API") as api:
            self.assertEqual(backend.translate("hello"), "через API")
        api.assert_called_once()
        notice = backend.take_notice()
        self.assertIn("model.bin missing", notice)
        self.assertNotIn("more details", notice, "only the first line of the reason is shown")

    def test_missing_model_falls_back_for_detection_too(self):
        self._nllb(_FakeNllb(load_error=NllbModelUnavailable("")))
        with mock.patch("translate.llm_client.detect_and_translate", return_value=("en", "через API")):
            self.assertEqual(backend.detect_and_translate("hello"), ("en", "через API"))
        self.assertIn("NllbModelUnavailable", backend.take_notice())

    def test_translation_error_of_a_loaded_model_is_not_hidden(self):
        self._nllb(_FakeNllb())
        with (
            mock.patch("translate.nllb_backend.translate", side_effect=NllbTranslationError("boom")),
            mock.patch("translate.llm_client.translate", side_effect=AssertionError("API called")),
        ):
            with self.assertRaises(NllbTranslationError):
                backend.translate("hello")

    def test_api_backend_passes_through(self):
        with (
            _config("TRANSLATION_BACKEND", "api"),
            mock.patch("translate.llm_client.translate", return_value="через API") as api,
        ):
            self.assertEqual(backend.translate("hello", target_lang="de", domain_id="games"), "через API")
        self.assertEqual(api.call_args.kwargs["target_lang"], "de")
        self.assertEqual(api.call_args.kwargs["domain_id"], "games")

    def test_a_new_call_clears_the_previous_notice(self):
        self._nllb(_FakeNllb(load_error=NllbModelUnavailable("gone")))
        with mock.patch("translate.llm_client.translate", return_value="x"):
            backend.translate("hello")
        with _config("TRANSLATION_BACKEND", "api"), mock.patch("translate.llm_client.translate", return_value="x"):
            backend.translate("hello")
        self.assertEqual(backend.take_notice(), "")


class TestPreload(unittest.TestCase):
    def test_nmt_and_api_need_no_loading(self):
        ok, message = backend.preload("deepl")
        self.assertTrue(ok)
        self.assertIn("DeepL API", message)
        self.assertTrue(backend.preload("api")[0])

    def test_loaded_model_reports_device_and_notice(self):
        fake = _FakeNllb(notice="CUDA unavailable")
        with mock.patch("translate.nllb_backend.get_backend", return_value=fake):
            ok, message = backend.preload("nllb")
        self.assertTrue(ok)
        self.assertIn("Device: CPU", message)
        self.assertIn("CUDA unavailable", message)
        self.assertIn(str(fake.model_dir), message)
        self.assertEqual(fake.take_notice(), "", "preload consumes the notice")

    def test_failures_are_returned_not_raised(self):
        for error in (NllbModelUnavailable("no model here"), OSError("disk error")):
            with mock.patch("translate.nllb_backend.get_backend", return_value=_FakeNllb(load_error=error)):
                ok, message = backend.preload("nllb")
            self.assertFalse(ok)
            self.assertIn(str(error), message)

    def test_reset_resets_both_backends(self):
        with (
            mock.patch("translate.llm_client.reset_client") as reset_api,
            mock.patch("translate.nllb_backend.reset_client", side_effect=RuntimeError("busy")) as reset_nllb,
        ):
            backend.reset()  # an NLLB failure is logged, not raised
        reset_api.assert_called_once()
        reset_nllb.assert_called_once()


if __name__ == "__main__":
    unittest.main()
