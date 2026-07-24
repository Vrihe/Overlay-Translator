"""
tests/test_domain_profiles.py — Unit tests for domain profiles and domain-aware translation cache.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import config
from cache import store
from translate.domain_manager import load_domain_profile, list_available_domains
from translate.llm_client import _build_system_prompt, translate


class TestDomainProfiles(unittest.TestCase):

    def test_list_available_domains(self):
        domains = list_available_domains()
        domain_ids = [d["id"] for d in domains]
        self.assertIn("general", domain_ids)
        self.assertIn("game", domain_ids)
        self.assertIn("documentation", domain_ids)
        self.assertIn("chat", domain_ids)

    def test_load_domain_profile_valid(self):
        profile = load_domain_profile("game")
        self.assertEqual(profile["id"], "game")
        self.assertEqual(profile["display_name"], "Игры")
        self.assertIn("игровую терминологию", profile["system_prompt"])
        self.assertTrue(len(profile["few_shot_examples"]) >= 2)

    def test_load_domain_profile_fallback_on_invalid(self):
        profile = load_domain_profile("non_existent_domain_xyz")
        self.assertEqual(profile["id"], "general")

    def test_build_system_prompt_includes_few_shots(self):
        prompt = _build_system_prompt("game", "ru", "en")
        self.assertIn("Critical Hit Chance", prompt)
        self.assertIn("Few-Shot Examples", prompt)

    def test_domain_cache_separation(self):
        text = "Unique Domain Test String 123"
        store.save_to_cache(text, "en", "ru", "game", "Игровой перевод 123")
        store.save_to_cache(text, "en", "ru", "documentation", "Документационный перевод 123")

        cached_game = store.get_cached(text, "en", "ru", "game")
        cached_doc = store.get_cached(text, "en", "ru", "documentation")

        self.assertEqual(cached_game, "Игровой перевод 123")
        self.assertEqual(cached_doc, "Документационный перевод 123")
        self.assertNotEqual(cached_game, cached_doc)


if __name__ == "__main__":
    unittest.main()
