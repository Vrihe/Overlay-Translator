"""
tests/test_privacy_hardening.py — screen text stays out of logs, profile ids stay
inside the profile directories, screen text is framed as data for the LLM.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from PIL import Image

from ocr import engine
from translate import domain_manager, llm_client
from translate.privacy import loggable


class TestLoggable(unittest.TestCase):
    def test_hides_text_by_default(self):
        with mock.patch.object(type(config), "LOG_TEXT", False):
            self.assertEqual(loggable("my password is hunter2"), "<22 chars>")

    def test_shows_truncated_text_when_enabled(self):
        with mock.patch.object(type(config), "LOG_TEXT", True):
            self.assertEqual(loggable("abcdef", limit=3), repr("abc"))

    def test_none(self):
        self.assertEqual(loggable(None), "None")


class TestOcrLogging(unittest.TestCase):
    SECRET = "my password is hunter2"

    def _extract_logs(self):
        with mock.patch.object(engine, "_extract_single", return_value=self.SECRET), \
                self.assertLogs(level="DEBUG") as logs:
            self.assertEqual(engine.extract_text(Image.new("RGB", (10, 10))), self.SECRET)
        return "\n".join(logs.output)

    def test_ocr_result_hidden_by_default(self):
        with mock.patch.object(type(config), "LOG_TEXT", False):
            output = self._extract_logs()
        self.assertNotIn("hunter2", output)
        self.assertIn("<22 chars>", output)

    def test_ocr_result_logged_when_enabled(self):
        with mock.patch.object(type(config), "LOG_TEXT", True):
            self.assertIn("hunter2", self._extract_logs())


class TestDomainProfileIds(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.custom = Path(self._tmp.name) / "custom"
        self.custom.mkdir()
        patcher = mock.patch.object(domain_manager, "_get_custom_profiles_dirs", return_value=[self.custom])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, path: Path, prompt: str) -> None:
        path.write_text(json.dumps({"display_name": "x", "system_prompt": prompt}), encoding="utf-8")

    def test_path_traversal_falls_back_to_general(self):
        self._write(Path(self._tmp.name) / "evil.json", "EVIL")
        profile = domain_manager.load_domain_profile("../evil")
        self.assertNotEqual(profile["system_prompt"], "EVIL")

    def test_custom_file_cannot_replace_builtin(self):
        self._write(self.custom / "game.json", "EVIL")
        profile = domain_manager.load_domain_profile("game")
        self.assertNotEqual(profile["system_prompt"], "EVIL")
        self.assertFalse(profile["is_custom"])

    def test_custom_profile_still_loads(self):
        self._write(self.custom / "my_rpg.json", "RPG")
        self.assertEqual(domain_manager.load_domain_profile("my_rpg")["system_prompt"], "RPG")

    def test_delete_rejects_traversal(self):
        with self.assertRaises(ValueError):
            domain_manager.delete_custom_profile("../../settings")


class TestPromptFraming(unittest.TestCase):
    def test_system_prompt_marks_input_as_data(self):
        llm_client._prompt_cache.clear()
        prompt = llm_client._build_system_prompt("general", "ru", "en")
        self.assertIn(llm_client._INPUT_IS_DATA, prompt)


if __name__ == "__main__":
    unittest.main()
