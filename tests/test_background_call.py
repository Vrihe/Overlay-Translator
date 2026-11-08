"""
tests/test_background_call.py — blocking calls (key and update checks) run off the
UI thread and report back on it; a result for a closed widget is dropped.

Runs offscreen; the "network" calls are plain functions.
"""

import sys
import threading
import unittest
from unittest import mock

from PyQt5.QtCore import QEventLoop, QObject, QTimer
from PyQt5.QtWidgets import QApplication, QPushButton

from tests.settings_widget_case import SettingsWidgetCase
from ui import background_call, settings_dialog

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def _wait(worker, timeout_ms: int = 5000) -> None:
    """Spin the event loop until *worker* finished and its queued result was delivered."""
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    if not worker.isFinished():
        loop.exec_()
    _APP.processEvents()


class TestRunInBackground(unittest.TestCase):
    def test_result_arrives_on_the_ui_thread_after_running_off_it(self):
        seen = {}

        def call():
            seen["call_thread"] = threading.current_thread()
            return 42

        def done(result, error):
            seen["done"] = (result, error, threading.current_thread())

        worker = background_call.run_in_background(call, done)
        _wait(worker)
        self.assertIsNot(seen["call_thread"], threading.main_thread())
        result, error, done_thread = seen["done"]
        self.assertEqual((result, error), (42, None))
        self.assertIs(done_thread, threading.main_thread())
        self.assertNotIn(worker, background_call._running)

    def test_exception_is_delivered_as_the_error(self):
        seen = []

        def call():
            raise ValueError("bad key")

        worker = background_call.run_in_background(call, lambda r, e: seen.append((r, e)))
        _wait(worker)
        self.assertIsNone(seen[0][0])
        self.assertIsInstance(seen[0][1], ValueError)

    def test_result_for_a_deleted_widget_is_dropped(self):
        seen = []
        gate = threading.Event()
        context = QObject()
        worker = background_call.run_in_background(lambda: gate.wait(5), lambda r, e: seen.append(r), context)
        self.assertIn(worker, background_call._running)  # kept alive while running
        from PyQt5 import sip

        sip.delete(context)
        gate.set()
        _wait(worker)
        self.assertEqual(seen, [])


class TestFirstRunDialogKeyCheck(unittest.TestCase):
    def test_validation_runs_in_the_background_and_saves_on_success(self):
        from unittest import mock

        from ui import first_run_dialog

        dlg = first_run_dialog.FirstRunDialog()
        self.addCleanup(dlg.deleteLater)
        dlg._key_input.setText("sk-test")
        with (
            mock.patch.object(first_run_dialog, "run_in_background") as background,
            mock.patch("settings.set_api_key") as store,
            mock.patch("translate.llm_client.reset_client"),
            mock.patch.object(first_run_dialog.QTimer, "singleShot"),
        ):
            dlg._on_save()
            store.assert_not_called()  # nothing saved before the check returns
            self.assertFalse(dlg._btn_save.isEnabled())
            _call, on_done, _ctx = background.call_args.args
            on_done(None, None)
        store.assert_called_once()
        self.assertEqual(store.call_args.args[1], "sk-test")

    def test_rejected_key_is_not_saved(self):
        from unittest import mock

        from ui import first_run_dialog

        dlg = first_run_dialog.FirstRunDialog()
        self.addCleanup(dlg.deleteLater)
        dlg._key_input.setText("sk-bad")
        with (
            mock.patch.object(first_run_dialog, "run_in_background") as background,
            mock.patch("settings.set_api_key") as store,
        ):
            dlg._on_save()
            background.call_args.args[1](None, RuntimeError("401"))
        store.assert_not_called()
        self.assertTrue(dlg._btn_save.isEnabled())
        self.assertTrue(dlg._key_input.isEnabled())

    def test_key_cannot_be_edited_or_resubmitted_while_checking(self):
        from unittest import mock

        from ui import first_run_dialog

        dlg = first_run_dialog.FirstRunDialog()
        self.addCleanup(dlg.deleteLater)
        dlg._key_input.setText("sk-test")
        with mock.patch.object(first_run_dialog, "run_in_background") as background:
            dlg._on_save()
            self.assertFalse(dlg._key_input.isEnabled())
            dlg._on_key_changed("sk-other")  # must not re-enable Save
            self.assertFalse(dlg._btn_save.isEnabled())
        background.assert_called_once()

    def test_key_validated_after_cancel_is_not_saved(self):
        from unittest import mock

        from ui import first_run_dialog

        dlg = first_run_dialog.FirstRunDialog()
        self.addCleanup(dlg.deleteLater)
        dlg._key_input.setText("sk-test")
        with (
            mock.patch.object(first_run_dialog, "run_in_background") as background,
            mock.patch("settings.set_api_key") as store,
        ):
            dlg._on_save()
            dlg.reject()  # user cancels while the check is still running
            background.call_args.args[1](None, None)
        store.assert_not_called()


class TestSettingsChecksAreExclusive(SettingsWidgetCase):
    def test_llm_check_locks_check_save_and_the_key_until_it_returns(self):
        w = self.widget
        w._key_input.setText("sk-test")
        with mock.patch.object(settings_dialog, "run_in_background") as background:
            w._on_check_llm_key()
            for widget in (w._btn_check_key, w._btn_save_key, w._key_input):
                self.assertFalse(widget.isEnabled())
            background.call_args.args[1](None, RuntimeError("401"))
        for widget in (w._btn_check_key, w._btn_save_key, w._key_input):
            self.assertTrue(widget.isEnabled())

    def test_nmt_test_button_is_locked_while_its_test_runs(self):
        button = QPushButton()
        with mock.patch.object(settings_dialog, "run_in_background") as background:
            self.widget._test_nmt_key("google", button)
            self.assertFalse(button.isEnabled())
            background.call_args.args[1](("en", "привет"), None)
        self.assertTrue(button.isEnabled())


class TestTraySerial(unittest.TestCase):
    def test_every_balloon_bumps_the_serial(self):
        from tray.tray_icon import TrayIcon

        with mock.patch.object(TrayIcon.__mro__[1], "showMessage") as qt_show:
            tray = mock.Mock(spec=TrayIcon)
            tray.message_serial = 0
            TrayIcon.showMessage(tray, "t", "m")
            TrayIcon.showMessage(tray, "t", "m")
        self.assertEqual(tray.message_serial, 2)
        self.assertEqual(qt_show.call_count, 2)


if __name__ == "__main__":
    unittest.main()
