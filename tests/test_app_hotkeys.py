"""
tests/test_app_hotkeys.py — the translate / settings hotkeys set in Settings → Hotkeys:
converting a captured QKeySequence, checking a new combination, the settings value
with its env override, and the settings page saving or rejecting an edit.

settings.json, presets and keyring are mocked; no global hook is installed.
"""

import os
import unittest
from unittest import mock

import config
from settings import hotkeys
from settings.hotkeys import SETTINGS, TRANSLATE, from_key_sequence, validate_app_hotkey
from tests.settings_widget_case import SettingsWidgetCase


def setUpModule():
    # Messages are matched in Russian whatever the machine's UI language setting is.
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


def _current(translate="ctrl+shift+r", settings="ctrl+shift+o"):
    return mock.patch.object(hotkeys, "current", side_effect=lambda role: translate if role == TRANSLATE else settings)


def _presets(*items):
    return mock.patch("settings.region_presets.load_presets", return_value=list(items))


class TestFromKeySequence(unittest.TestCase):
    def test_conversions(self):
        cases = {
            "Ctrl+Shift+R": "ctrl+shift+r",
            "Ctrl+Shift+R, Ctrl+A": "ctrl+shift+r",  # only the first chord
            "Meta+T": "windows+t",
            "Ctrl+PgUp": "ctrl+page up",
            "Alt+Del": "alt+delete",
            "F8": "f8",
            "Ctrl++": "ctrl++",
            "": "",
        }
        for text, expected in cases.items():
            self.assertEqual(from_key_sequence(text), expected, text)


class TestValidateAppHotkey(unittest.TestCase):
    def test_valid_combination_is_normalised(self):
        with _current(), _presets():
            self.assertEqual(validate_app_hotkey("Ctrl+Alt+T", TRANSLATE), "ctrl+alt+t")

    def test_function_key_alone_is_allowed(self):
        with _current(), _presets():
            self.assertEqual(validate_app_hotkey("f8", TRANSLATE), "f8")

    def test_single_ordinary_key_is_rejected(self):
        with _current(), _presets():
            for key in ("r", "space", "1"):
                with self.assertRaisesRegex(ValueError, "Ctrl, Alt, Shift"):
                    validate_app_hotkey(key, TRANSLATE)

    def test_empty_and_invalid(self):
        with _current(), _presets():
            with self.assertRaises(ValueError):
                validate_app_hotkey("", TRANSLATE)
            with self.assertRaisesRegex(ValueError, "Некорректная комбинация"):
                validate_app_hotkey("ctrl+not_a_key_xyz", TRANSLATE)

    def test_conflict_with_the_other_app_hotkey(self):
        with _current(), _presets():
            with self.assertRaisesRegex(ValueError, "другого действия"):
                validate_app_hotkey("ctrl+shift+o", TRANSLATE)
            with self.assertRaisesRegex(ValueError, "другого действия"):
                validate_app_hotkey("ctrl+shift+r", SETTINGS)

    def test_conflict_with_a_preset(self):
        with _current(), _presets({"name": "Чат", "hotkey": "ctrl+alt+1"}):
            with self.assertRaisesRegex(ValueError, "Чат"):
                validate_app_hotkey("Ctrl+Alt+1", SETTINGS)


class TestSettingsHotkeyValue(unittest.TestCase):
    def test_settings_hotkey_comes_from_settings_json(self):
        env = {k: v for k, v in os.environ.items() if k.upper() != "SETTINGS_HOTKEY"}
        # config replaces itself in sys.modules, so its reads are patched at the source.
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("settings.config_manager.get", side_effect=lambda key: {"settings_hotkey": "ctrl+alt+s"}[key]),
        ):
            self.assertEqual(config.SETTINGS_HOTKEY, "ctrl+alt+s")

    def test_env_var_overrides(self):
        with mock.patch.dict(os.environ, {"SETTINGS_HOTKEY": "ctrl+f12"}):
            self.assertEqual(config.SETTINGS_HOTKEY, "ctrl+f12")

    def test_defaults(self):
        from settings.config_manager import DEFAULTS

        self.assertEqual(DEFAULTS["hotkey"], "ctrl+shift+r")
        self.assertEqual(DEFAULTS["settings_hotkey"], "ctrl+shift+o")


class TestHotkeyEditing(SettingsWidgetCase):
    """The settings page with settings.json, keyring and backends mocked."""

    def setUp(self):
        super().setUp()
        self.changed = mock.Mock()
        self.widget.hotkeys_changed.connect(self.changed)

    def test_a_valid_edit_is_saved_and_announced(self):
        self.widget._apply_hotkey(TRANSLATE, "ctrl+alt+t")
        self.assertEqual(self.disk["hotkey"], "ctrl+alt+t")
        self.changed.assert_called_once()
        self.assertEqual(self.widget._hotkey_edits[TRANSLATE].keySequence().toString(), "Ctrl+Alt+T")

    def test_a_rejected_edit_restores_the_saved_hotkey(self):
        self.widget._apply_hotkey(TRANSLATE, "ctrl+shift+o")  # the settings hotkey
        self.assertEqual(self.disk["hotkey"], "ctrl+shift+r")
        self.changed.assert_not_called()
        self.assertIn("⚠", self.widget._hotkey_status.text())
        self.assertEqual(self.widget._hotkey_edits[TRANSLATE].keySequence().toString(), "Ctrl+Shift+R")

    def test_unchanged_value_does_nothing(self):
        self.writes.clear()
        self.widget._apply_hotkey(SETTINGS, "ctrl+shift+o")
        self.assertEqual(self.writes, [])
        self.changed.assert_not_called()

    def test_focus_pauses_and_resumes_the_global_hotkeys(self):
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QFocusEvent

        capture = mock.Mock()
        self.widget.hotkey_capture.connect(capture)
        edit = self.widget._hotkey_edits[SETTINGS]
        self.widget.eventFilter(edit, QFocusEvent(QEvent.FocusIn))
        self.widget.eventFilter(edit, QFocusEvent(QEvent.FocusOut))
        self.assertEqual([c.args for c in capture.call_args_list], [(True,), (False,)])


if __name__ == "__main__":
    unittest.main()
