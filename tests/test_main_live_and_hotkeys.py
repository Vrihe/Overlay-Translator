"""
tests/test_main_live_and_hotkeys.py — two TranslatorApp guards tested on a stub `self`:
a stale LiveMonitor change never starts a translation, and a hotkey that fails to
register is reported in the tray instead of only in the log.

No QApplication, no keyboard hook: the methods are called unbound on a Mock.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import main


class TestLiveRegionChanged(unittest.TestCase):
    def test_current_monitor_starts_a_live_translation(self):
        app = mock.Mock()
        monitor = object()
        app._live_monitor = monitor
        main.TranslatorApp._on_live_region_changed(app, monitor, 10, 20, 110, 70)
        app._start_translation_pipeline.assert_called_once()
        args, kwargs = app._start_translation_pipeline.call_args
        self.assertEqual(args[:4], (10, 20, 110, 70))
        self.assertTrue(kwargs["live"])

    def test_change_queued_before_stop_is_dropped(self):
        app = mock.Mock()
        app._live_monitor = None  # stopped
        main.TranslatorApp._on_live_region_changed(app, object(), 0, 0, 10, 10)
        app._start_translation_pipeline.assert_not_called()

    def test_change_from_a_replaced_monitor_is_dropped(self):
        app = mock.Mock()
        app._live_monitor = object()  # restarted with a new monitor
        main.TranslatorApp._on_live_region_changed(app, object(), 0, 0, 10, 10)
        app._start_translation_pipeline.assert_not_called()


class TestHotkeyRegistration(unittest.TestCase):
    def test_failed_hotkey_is_shown_in_the_tray(self):
        app = mock.Mock()
        app._app_hotkey_handles = []
        app._hotkeys_paused = False
        with (
            # config is a live facade with read-only properties: swap the whole name.
            mock.patch.object(main, "config", SimpleNamespace(HOTKEY="ctrl+bogus", SETTINGS_HOTKEY="ctrl+shift+o")),
            mock.patch.object(main.keyboard, "add_hotkey", side_effect=[ValueError("bad"), "handle"]),
            self.assertLogs(level="ERROR"),
        ):
            main.TranslatorApp._register_app_hotkeys(app)
        app._tray.showMessage.assert_called_once()
        self.assertIn("ctrl+bogus", app._tray.showMessage.call_args.args[1])
        self.assertEqual(app._app_hotkey_handles, ["handle"])


if __name__ == "__main__":
    unittest.main()
