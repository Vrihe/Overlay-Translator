"""
tests/test_settings_autosave.py — settings save themselves; restart-only ones light "Сохранить".

Builds SettingsWidget offscreen with settings.json, keyring and the backends mocked
(no file is written, no network, no model is loaded).
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication, QMessageBox

from settings import config_manager

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class TestSettingsAutosave(unittest.TestCase):

    def setUp(self):
        self.disk = dict(config_manager.DEFAULTS)
        self.disk.update(ui_theme="amber", ui_language="ru", target_language="ru",
                         translation_backend="api")
        self.writes = []

        def fake_save(cfg):
            self.writes.append(dict(cfg))
            self.disk = {**self.disk, **cfg}
            config_manager._cache = dict(self.disk)

        config_manager._cache = dict(self.disk)
        patches = [
            mock.patch.object(config_manager, "save_config", side_effect=fake_save),
            mock.patch.object(config_manager, "load_config", side_effect=lambda: dict(self.disk)),
            mock.patch.object(config_manager, "set_value",
                              side_effect=lambda k, v: fake_save({**self.disk, k: v})),
            mock.patch("settings.save_primary_provider"),
            mock.patch("settings.set_fallback_enabled"),
            mock.patch("settings.get_api_key", return_value=None),
            mock.patch("settings.get_primary_provider", return_value="openrouter"),
            mock.patch("settings.is_fallback_enabled", return_value=True),
            mock.patch("translate.backend.reset"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(setattr, config_manager, "_cache", None)

        from ui import settings_dialog
        self.llm_reset = mock.patch.object(settings_dialog, "reset_client").start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(settings_dialog.SettingsWidget, "_detect_gpu_info",
                          staticmethod(lambda: "")).start()
        self.widget = settings_dialog.SettingsWidget()

    def test_opening_writes_nothing_and_save_is_off(self):
        self.assertEqual(self.writes, [])
        self.assertFalse(self.widget._btn_save.isEnabled())

    def test_change_is_saved_once_after_the_debounce(self):
        w = self.widget
        w._chk_streaming.setChecked(not w._chk_streaming.isChecked())
        w._tokens_spin.setValue(w._tokens_spin.value() + 50)
        self.assertEqual(self.writes, [])  # still within the debounce window
        w._flush_autosave()
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.disk["enable_streaming"], w._chk_streaming.isChecked())
        self.assertEqual(self.disk["llm_max_tokens"], w._tokens_spin.value())
        self.llm_reset.assert_called()

    def test_target_language_autosaves(self):
        w = self.widget
        w._lang_combo.setCurrentIndex(w._lang_combo.findData("de"))
        w._flush_autosave()
        self.assertEqual(self.disk["target_language"], "de")

    def test_restart_only_setting_lights_save_and_is_not_autosaved(self):
        w = self.widget
        w._theme_combo.setCurrentIndex(w._theme_combo.findData("cyan"))
        w._flush_autosave()
        self.assertTrue(w._btn_save.isEnabled())
        self.assertEqual(self.disk["ui_theme"], "amber")
        w._theme_combo.setCurrentIndex(w._theme_combo.findData("amber"))
        self.assertFalse(w._btn_save.isEnabled())

    def test_save_writes_restart_settings_and_requests_restart(self):
        w = self.widget
        requested = []
        w.restart_requested.connect(lambda: requested.append(True))
        w._theme_combo.setCurrentIndex(w._theme_combo.findData("crimson"))
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            w._on_save()
        self.assertEqual(self.disk["ui_theme"], "crimson")
        self.assertEqual(requested, [True])
        self.assertFalse(w._btn_save.isEnabled())

    def test_declining_restart_still_saves(self):
        w = self.widget
        requested = []
        w.restart_requested.connect(lambda: requested.append(True))
        w._ui_lang_combo.setCurrentIndex(w._ui_lang_combo.findData("en"))
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            w._on_save()
        self.assertEqual(self.disk["ui_language"], "en")
        self.assertEqual(requested, [])

    def test_reload_writes_nothing(self):
        self.widget.reload()
        self.assertEqual(self.writes, [])


if __name__ == "__main__":
    unittest.main()
