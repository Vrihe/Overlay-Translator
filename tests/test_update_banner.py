"""
tests/test_update_banner.py — the main window checks for updates at launch and every
30 minutes, offers each new version once and never re-checks while an update downloads.

The window is built offscreen; the update check worker never runs (no network).
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

from ui import main_window
from ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class _IdleWorker:
    """Stands in for _UpdateCheckWorker: the result is delivered by the test."""

    started = 0

    def __init__(self):
        self.update_done = mock.Mock()
        self.finished = mock.Mock()

    def start(self):
        _IdleWorker.started += 1


class TestUpdateChecks(unittest.TestCase):
    def setUp(self):
        _IdleWorker.started = 0
        patcher = mock.patch.object(main_window, "_UpdateCheckWorker", _IdleWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.tray = mock.Mock()
        self.window.set_tray_icon(self.tray)

    def test_checked_at_launch_and_every_30_minutes(self):
        self.assertEqual(_IdleWorker.started, 1)
        self.assertTrue(self.window._update_timer.isActive())
        self.assertEqual(self.window._update_timer.interval(), 30 * 60 * 1000)

    def test_no_second_check_while_one_runs_or_an_update_downloads(self):
        self.window._start_update_check()  # the launch check is still "running"
        self.assertEqual(_IdleWorker.started, 1)
        self.window._update_worker = None
        self.window._update_install_worker = mock.Mock()
        self.window._start_update_check()
        self.assertEqual(_IdleWorker.started, 1)

    def test_each_version_is_announced_once(self):
        with mock.patch("updater.install_update.can_self_update", return_value=True):
            self.window._on_update_check_finished(True, "v9.9.9", "https://example.invalid")
            self.window._on_update_check_finished(True, "v9.9.9", "https://example.invalid")
        self.assertEqual(self.tray.showMessage.call_count, 1)
        self.assertFalse(self.window._update_banner.isHidden())
        with mock.patch("updater.install_update.can_self_update", return_value=True):
            self.window._on_update_check_finished(True, "v9.9.10", "https://example.invalid")
        self.assertEqual(self.tray.showMessage.call_count, 2)


if __name__ == "__main__":
    unittest.main()
