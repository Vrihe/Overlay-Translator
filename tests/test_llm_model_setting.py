"""
tests/test_llm_model_setting.py — the LLM model is a free-text OpenRouter id typed in
Settings (no preset list): it loads as saved, saves as typed, empty saves the default,
and every built-in fallback uses that one default.

SettingsWidget is built offscreen with settings.json and keyring mocked.
"""

import os
import re
import unittest
from pathlib import Path

from settings import config_manager
from tests.settings_widget_case import SettingsWidgetCase


class TestModelField(SettingsWidgetCase):
    def _load(self, model):
        self.disk["llm_model"] = model
        config_manager._cache = dict(self.disk)
        self.widget.reload()

    def test_saved_model_is_shown_as_typed(self):
        self._load("some-lab/some-model:free")
        self.assertEqual(self.widget._model_edit.text(), "some-lab/some-model:free")

    def test_typed_model_is_saved(self):
        self.widget._model_edit.setText("  vendor/new-model  ")
        self.widget._model_edit.editingFinished.emit()
        self.widget._flush_autosave()
        self.assertEqual(self.disk["llm_model"], "vendor/new-model")

    def test_empty_field_saves_the_default(self):
        self._load("vendor/old-model")
        self.widget._model_edit.setText("")
        self.widget._model_edit.editingFinished.emit()
        self.widget._flush_autosave()
        self.assertEqual(self.disk["llm_model"], config_manager.DEFAULTS["llm_model"])

    def test_no_preset_list_is_left(self):
        from ui import settings_dialog

        self.assertFalse(hasattr(settings_dialog, "_OPENROUTER_MODELS"))
        self.assertFalse(hasattr(self.widget, "_model_combo"))

    def test_no_dead_engine_switch(self):
        # "Движок перевода" looked like the backend choice but the pipeline never read it.
        self.assertFalse(hasattr(self.widget, "_engine_combo"))


class TestOneDefaultModel(unittest.TestCase):
    def test_static_openrouter_model_matches_the_settings_default(self):
        import config

        if os.environ.get("OPENROUTER_MODEL"):
            self.skipTest("OPENROUTER_MODEL is overridden in this environment")
        self.assertEqual(config.OPENROUTER_MODEL, config_manager.DEFAULTS["llm_model"])

    def test_no_model_id_is_hardcoded_elsewhere(self):
        # Free models disappear from OpenRouter: a stale id hidden in a fallback broke
        # translation before. Only DEFAULTS (and its mirror in config.py) name a model.
        root = Path(__file__).resolve().parents[1]
        pattern = re.compile(r"[\"'][\w.-]+/[\w.-]+:free[\"']")
        for folder in ("translate", "ui", "settings"):
            for path in (root / folder).glob("*.py"):
                if path.name == "config_manager.py":
                    continue
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
