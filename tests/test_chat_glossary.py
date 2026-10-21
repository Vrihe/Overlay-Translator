"""
tests/test_chat_glossary.py — game-chat glossary used before local NLLB translation.

Covers:
  • Known terms are replaced with their meaning; ordinary text is untouched.
  • Protected terms are masked as [n] and restored in their original spelling.
  • Patterns: lf<N>m, prices like 500g / 2kk; whitespace (OCR newlines) is preserved.
  • NllbBackend._translate_text: glossary only for English, unmasked fallback when
    the model drops a placeholder, no model call for a protected-terms-only line.
  • The shipped glossary file loads and contains the core terms.
"""

import unittest
from unittest.mock import patch

from translate import chat_glossary
from translate.chat_glossary import prepare, restore

TERMS = {
    "wts": "want to sell",
    "pm": "private message",
    "gg": "good game",
    "wp": "well played",
    "valorant": None,
    "kekw": "haha",
}


class TestPrepare(unittest.TestCase):
    def test_expands_known_terms(self):
        p = prepare("wts leather armor, pm me", TERMS)
        self.assertEqual(p.text, "want to sell leather armor, private message me")
        self.assertEqual(p.expanded, ["wts", "pm"])
        self.assertEqual(p.restore, {})

    def test_ordinary_text_untouched(self):
        p = prepare("the weather is nice today", TERMS)
        self.assertEqual(p.text, "the weather is nice today")
        self.assertFalse(p.changed)

    def test_capitalises_expansion_at_line_start(self):
        self.assertEqual(prepare("WTS sword", TERMS).text, "Want to sell sword")

    def test_masks_protected_terms(self):
        p = prepare("kekw that was Valorant!", TERMS)
        self.assertEqual(p.text, "haha that was [1]!")
        self.assertEqual(p.unmasked, "haha that was Valorant!")
        self.assertEqual(p.restore, {"[1]": "Valorant"})

    def test_patterns(self):
        self.assertEqual(prepare("lf2m for dungeon", TERMS).text, "we need 2 more players for dungeon")
        self.assertEqual(prepare("wts sword 500g", TERMS).text, "want to sell sword 500 gold")
        self.assertEqual(prepare("2kk", TERMS).text, "2 million")
        self.assertEqual(prepare("wait 2m", TERMS).text, "wait 2m")  # minutes or million: left alone

    def test_preserves_newlines(self):
        self.assertEqual(prepare("gg\nwp all", TERMS).text, "good game\nwell played all")


class TestRestore(unittest.TestCase):
    def test_restores_original_spelling(self):
        p = prepare("that was Valorant", TERMS)
        self.assertEqual(restore("это была [1]", p), "это была Valorant")

    def test_lost_placeholder_returns_none(self):
        p = prepare("that was Valorant", TERMS)
        self.assertIsNone(restore("это была игра", p))


class TestBackendIntegration(unittest.TestCase):
    def setUp(self):
        from translate.nllb_backend import NllbBackend

        self.backend = NllbBackend.__new__(NllbBackend)
        self.calls = []
        self.backend._raw_translate = lambda text, src, tgt: self.calls.append(text) or f"<{text}>"
        patcher = patch.object(chat_glossary, "load_terms", return_value=TERMS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_english_source_is_expanded(self):
        out = self.backend._translate_text("wts sword", "en", "eng_Latn", "rus_Cyrl")
        self.assertEqual(self.calls, ["want to sell sword"])
        self.assertEqual(out, "<want to sell sword>")

    def test_other_source_untouched(self):
        self.backend._translate_text("wts sword", "de", "deu_Latn", "rus_Cyrl")
        self.assertEqual(self.calls, ["wts sword"])

    def test_disabled_by_config(self):
        with patch("config.NLLB_GLOSSARY", False, create=True):
            self.backend._translate_text("wts sword", "en", "eng_Latn", "rus_Cyrl")
        self.assertEqual(self.calls, ["wts sword"])

    def test_restores_protected_term(self):
        out = self.backend._translate_text("gg on Valorant", "en", "eng_Latn", "rus_Cyrl")
        self.assertEqual(out, "<good game on Valorant>")

    def test_falls_back_when_placeholder_lost(self):
        self.backend._raw_translate = lambda text, src, tgt: self.calls.append(text) or "lost it"
        out = self.backend._translate_text("gg on Valorant", "en", "eng_Latn", "rus_Cyrl")
        self.assertEqual(self.calls, ["good game on [1]", "good game on Valorant"])
        self.assertEqual(out, "lost it")

    def test_protected_only_line_skips_model(self):
        self.assertEqual(self.backend._translate_text("Valorant!", "en", "eng_Latn", "rus_Cyrl"), "Valorant!")
        self.assertEqual(self.calls, [])


class TestShippedGlossary(unittest.TestCase):
    def test_core_terms(self):
        terms = chat_glossary.load_terms(chat_glossary.GLOSSARY_PATH)
        self.assertGreater(len(terms), 500)
        for term in ("gg", "wp", "wts", "wtb", "lfg", "idk", "ty", "brb"):
            self.assertTrue(terms.get(term), term)
        self.assertGreaterEqual(chat_glossary.glossary_version(), 1)


if __name__ == "__main__":
    unittest.main()
