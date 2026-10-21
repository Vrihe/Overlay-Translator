"""
tests/test_backend_default.py — keyless Google is the default; the key dialog is LLM-only.
"""

import os
import unittest
from unittest import mock

import config
from settings import config_manager
from translate import backend


def _backend_is(value):
    return mock.patch.object(type(config), "TRANSLATION_BACKEND", new_callable=mock.PropertyMock,
                             return_value=value)


class TestDefaultBackend(unittest.TestCase):

    def test_defaults_to_google(self):
        self.assertEqual(config_manager.DEFAULTS["translation_backend"], "google")
        self.assertEqual(backend.DEFAULT_BACKEND, backend.BACKEND_GOOGLE)

    def test_missing_or_unknown_value_falls_back_to_google(self):
        for value in (None, "", "something-else"):
            with _backend_is(value):
                self.assertEqual(backend.get_active_backend(), backend.BACKEND_GOOGLE, value)

    def test_explicit_choice_is_kept(self):
        for value in ("api", "deepl", "azure", "nllb", " Google "):
            with _backend_is(value):
                self.assertEqual(backend.get_active_backend(), value.strip().lower())


class TestNeedsLlmKey(unittest.TestCase):

    def setUp(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_llm_backends_never_ask(self):
        with mock.patch("settings.get_api_key", return_value=None) as get_key:
            for value in ("google", "deepl", "azure", "nllb", None):
                with _backend_is(value):
                    self.assertFalse(backend.needs_llm_key(), value)
            get_key.assert_not_called()

    def test_llm_without_key_asks(self):
        with _backend_is("api"), mock.patch("settings.get_api_key", return_value=None):
            self.assertTrue(backend.needs_llm_key())

    def test_llm_with_a_stored_or_env_key_does_not_ask(self):
        with _backend_is("api"):
            with mock.patch("settings.get_api_key",
                            side_effect=lambda p: "k" if p == "anthropic" else None):
                self.assertFalse(backend.needs_llm_key())
            with mock.patch("settings.get_api_key", return_value=None), \
                    mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "k"}):
                self.assertFalse(backend.needs_llm_key())


class TestUsesLangid(unittest.TestCase):

    def test_nmt_backends_skip_langid(self):
        for value in ("google", "deepl", "azure", None):
            with _backend_is(value):
                self.assertFalse(backend.uses_langid(), value)

    def test_llm_and_local_model_use_langid(self):
        for value in ("api", "nllb"):
            with _backend_is(value):
                self.assertTrue(backend.uses_langid(), value)


if __name__ == "__main__":
    unittest.main()
