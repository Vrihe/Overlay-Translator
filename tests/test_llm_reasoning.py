"""
tests/test_llm_reasoning.py — a reasoning model's thinking never reaches the translation.

The OpenRouter client is mocked (no network): streamed reasoning deltas, a non-streamed
reply whose content is empty but whose ``reasoning`` is filled, and <think> blocks
inline in the answer.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from i18n import set_language
from translate import llm_client


def _chunk(content=None, reasoning=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _reply(content=None, reasoning=None):
    msg = SimpleNamespace(content=content, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class TestStripReasoning(unittest.TestCase):
    def test_removes_think_blocks(self):
        self.assertEqual(llm_client._strip_reasoning("<think>plan…</think>Привет"), "Привет")
        self.assertEqual(llm_client._strip_reasoning("<THINKING>x\ny</THINKING> Да"), " Да")

    def test_unclosed_block_hides_the_rest(self):
        self.assertEqual(llm_client._strip_reasoning("Привет <think>still thinking"), "Привет ")

    def test_plain_text_unchanged(self):
        self.assertEqual(llm_client._strip_reasoning("Мало здоровья!"), "Мало здоровья!")


class TestOpenRouterReasoning(unittest.TestCase):
    def setUp(self):
        set_language("ru")
        self.addCleanup(set_language, None)
        self.client = MagicMock()

    def _call(self, on_chunk=None):
        return llm_client._call_provider(self.client, "openrouter", "m", "sys", "user", on_chunk=on_chunk)

    def test_stream_shows_only_the_answer(self):
        self.client.chat.completions.create.return_value = iter(
            [
                _chunk(reasoning="The user wants a translation. Let me think"),
                _chunk(reasoning="… done."),
                _chunk(content="Привет"),
                _chunk(content=", мир"),
            ]
        )
        shown = []
        self.assertEqual(self._call(on_chunk=shown.append), "Привет, мир")
        self.assertEqual(shown, ["Привет", "Привет, мир"])

    def test_stream_hides_inline_think_block(self):
        self.client.chat.completions.create.return_value = iter(
            [
                _chunk(content="<think>translate"),
                _chunk(content=" it</think>"),
                _chunk(content="Да"),
            ]
        )
        shown = []
        self.assertEqual(self._call(on_chunk=shown.append), "Да")
        self.assertEqual(shown, ["Да"])

    def test_reasoning_only_reply_is_an_error_not_a_translation(self):
        # Stream: thinking only → falls back to the plain call, which also has no answer.
        self.client.chat.completions.create.side_effect = [
            iter([_chunk(reasoning="Long chain of thought that ran out of tokens")]),
            _reply(content=None, reasoning="Long chain of thought that ran out of tokens"),
        ]
        shown = []
        with self.assertRaises(RuntimeError):
            self._call(on_chunk=shown.append)
        self.assertEqual(shown, [])

    def test_plain_call_asks_to_exclude_reasoning(self):
        self.client.chat.completions.create.return_value = _reply(content="Привет")
        self.assertEqual(self._call(), "Привет")
        kwargs = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["extra_body"], {"include_reasoning": False})


if __name__ == "__main__":
    unittest.main()
