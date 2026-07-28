"""
tests/test_llm_resilience.py — unit tests for LLM retry & provider fallback resilience.
"""

import unittest
from unittest.mock import MagicMock, patch

import anthropic
import openai

import config
import settings
from translate import llm_client


class TestLLMResilience(unittest.TestCase):

    def setUp(self):
        llm_client.reset_client()

    def tearDown(self):
        llm_client.reset_client()

    @patch("translate.llm_client.settings.get_primary_provider", return_value="anthropic")
    @patch("translate.llm_client.settings.is_fallback_enabled", return_value=True)
    @patch("translate.llm_client.settings.get_api_key")
    @patch("translate.llm_client.time.sleep")
    def test_retry_on_transient_error(self, mock_sleep, mock_get_key, mock_fallback, mock_primary):
        """Transient error (RateLimitError) retries on same provider and succeeds on attempt 2."""
        mock_get_key.side_effect = lambda provider: "fake_key_123" if provider in ("anthropic", "openrouter") else None

        mock_anthropic_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Retry success translation")]

        # Attempt 0: RateLimitError, Attempt 1: Success
        err_response = MagicMock()
        err_response.status_code = 429
        mock_anthropic_client.messages.create.side_effect = [
            anthropic.RateLimitError("Rate limit exceeded", response=err_response, body={}),
            mock_msg,
        ]

        with patch.dict(llm_client._clients_cache, {"anthropic": mock_anthropic_client}):
            model_map = {"anthropic": "claude-haiku", "openrouter": "gpt-oss"}
            result, provider = llm_client._call_with_resilience("sys", "user", model_map)

            self.assertEqual(result, "Retry success translation")
            self.assertEqual(provider, "anthropic")
            self.assertEqual(mock_anthropic_client.messages.create.call_count, 2)
            mock_sleep.assert_called_once()

    @patch("translate.llm_client.settings.get_primary_provider", return_value="anthropic")
    @patch("translate.llm_client.settings.is_fallback_enabled", return_value=True)
    @patch("translate.llm_client.settings.get_api_key")
    def test_fallback_on_non_retryable_error(self, mock_get_key, mock_fallback, mock_primary):
        """Non-retryable error (AuthenticationError) immediately skips retries and falls back to secondary provider."""
        mock_get_key.side_effect = lambda provider: "fake_key_123" if provider in ("anthropic", "openrouter") else None

        mock_anthropic_client = MagicMock()
        err_response = MagicMock()
        err_response.status_code = 401
        mock_anthropic_client.messages.create.side_effect = anthropic.AuthenticationError(
            "Invalid API key", response=err_response, body={}
        )

        mock_openrouter_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Fallback translation"
        mock_response = MagicMock(choices=[mock_choice])
        mock_openrouter_client.chat.completions.create.return_value = mock_response

        with patch.dict(llm_client._clients_cache, {
            "anthropic": mock_anthropic_client,
            "openrouter": mock_openrouter_client,
        }):
            model_map = {"anthropic": "claude-haiku", "openrouter": "gpt-oss"}
            result, provider = llm_client._call_with_resilience("sys", "user", model_map)

            self.assertEqual(result, "Fallback translation")
            self.assertEqual(provider, "openrouter")
            # Anthropic should be attempted only once (no retries for auth error)
            self.assertEqual(mock_anthropic_client.messages.create.call_count, 1)

    @patch("translate.llm_client.settings.get_primary_provider", return_value="openrouter")
    @patch("translate.llm_client.settings.is_fallback_enabled", return_value=True)
    @patch("translate.llm_client.settings.get_api_key")
    @patch("translate.llm_client.time.sleep")
    def test_all_providers_fail_raises_runtime_error(self, mock_sleep, mock_get_key, mock_fallback, mock_primary):
        """When all providers in chain fail all attempts, RuntimeError details all failures."""
        mock_get_key.side_effect = lambda provider: "fake_key_123" if provider in ("anthropic", "openrouter") else None

        mock_or_client = MagicMock()
        mock_or_client.chat.completions.create.side_effect = Exception("OpenRouter down")

        mock_ant_client = MagicMock()
        mock_ant_client.messages.create.side_effect = Exception("Anthropic down")

        with patch.dict(llm_client._clients_cache, {
            "openrouter": mock_or_client,
            "anthropic": mock_ant_client,
        }):
            model_map = {"openrouter": "m1", "anthropic": "m2"}
            with self.assertRaises(RuntimeError) as ctx:
                llm_client._call_with_resilience("sys", "user", model_map)

            err_text = str(ctx.exception)
            self.assertIn("Все провайдеры недоступны", err_text)
            self.assertIn("openrouter", err_text)
            self.assertIn("anthropic", err_text)

    @patch("translate.llm_client.settings.get_api_key")
    def test_get_provider_chain_fallback_toggle(self, mock_get_key):
        """get_provider_chain returns 2 providers when fallback enabled, 1 provider when disabled."""
        mock_get_key.side_effect = lambda provider: "key_val" if provider in ("openrouter", "anthropic") else None

        with patch("translate.llm_client.settings.get_primary_provider", return_value="openrouter"), \
             patch("translate.llm_client.settings.is_fallback_enabled", return_value=True):
            chain = llm_client.get_provider_chain()
            self.assertEqual(chain, ["openrouter", "anthropic"])

        with patch("translate.llm_client.settings.get_primary_provider", return_value="openrouter"), \
             patch("translate.llm_client.settings.is_fallback_enabled", return_value=False):
            chain = llm_client.get_provider_chain()
            self.assertEqual(chain, ["openrouter"])

    def test_reset_client_clears_cache(self):
        """reset_client clears cached clients."""
        llm_client._clients_cache["openrouter"] = MagicMock()
        llm_client._clients_cache["anthropic"] = MagicMock()
        self.assertEqual(len(llm_client._clients_cache), 2)

        llm_client.reset_client()
        self.assertEqual(len(llm_client._clients_cache), 0)


if __name__ == "__main__":
    unittest.main()
