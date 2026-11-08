"""
tests/test_main_live_and_hotkeys.py — two TranslatorApp guards tested on a stub `self`:
a stale LiveMonitor change never starts a translation, and a hotkey that fails to
register is reported in the tray instead of only in the log.

No QApplication, no keyboard hook: the methods are called unbound on a Mock.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from tests.main_import import import_main

main = import_main()


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


class TestSelectorEsc(unittest.TestCase):
    """Esc must cancel the selector even though Windows keeps the focus elsewhere."""

    def _app(self):
        app = mock.Mock()
        app._selector_esc_handle = None
        app._hotkeys_paused = False
        return app

    def test_esc_is_hooked_while_the_selector_is_up_and_unhooked_after(self):
        app = self._app()
        with mock.patch.object(main.keyboard, "add_hotkey", return_value="esc-handle") as add:
            main.TranslatorApp._hook_selector_esc(app)
        self.assertEqual(add.call_args.args[0], "esc")
        self.assertTrue(add.call_args.kwargs["suppress"])
        self.assertEqual(app._selector_esc_handle, "esc-handle")
        main.TranslatorApp._on_selector_destroyed(app)
        app._unhook_selector_esc.assert_called_once()
        self.assertIsNone(app._selector)

    def test_unhook_removes_the_handle_once(self):
        app = self._app()
        app._selector_esc_handle = "esc-handle"
        with mock.patch.object(main.keyboard, "remove_hotkey") as remove:
            main.TranslatorApp._unhook_selector_esc(app)
            main.TranslatorApp._unhook_selector_esc(app)
        remove.assert_called_once_with("esc-handle")
        self.assertIsNone(app._selector_esc_handle)

    def test_no_hook_while_hotkeys_are_paused(self):
        app = self._app()
        app._hotkeys_paused = True
        with mock.patch.object(main.keyboard, "add_hotkey") as add:
            main.TranslatorApp._hook_selector_esc(app)
        add.assert_not_called()

    def test_global_esc_cancels_the_selector(self):
        app = self._app()
        main.TranslatorApp._cancel_selector(app)
        app._selector.cancel.assert_called_once()

    def test_selector_cancel_emits_once(self):
        import sys

        from PyQt5.QtWidgets import QApplication

        from overlay.selector import RegionSelector

        _qt = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
        selector = RegionSelector()
        selector.setAttribute(main.Qt.WA_DeleteOnClose, False)
        self.addCleanup(selector.deleteLater)
        cancelled = mock.Mock()
        selector.selection_cancelled.connect(cancelled)
        selector.show()
        selector.cancel()
        selector.cancel()  # a second Esc after it closed
        cancelled.assert_called_once()
        self.assertFalse(selector.isVisible())


if __name__ == "__main__":
    unittest.main()
