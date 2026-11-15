"""
tests/test_main_window_tabs.py — the main window's feature tabs and the Home switches:
the rail order, the switches asking to start / stop subtitles and monitoring and following
the real state, and the links from the tabs to their settings sections.

The window is built offscreen; the update check, settings.json, the region presets, the
sound devices and the model lookup are faked — nothing is started.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

from settings import config_manager
from ui import main_window
from ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class _IdleWorker:
    def __init__(self):
        self.update_done = mock.Mock()
        self.finished = mock.Mock()

    def start(self):
        pass


class _WindowCase(unittest.TestCase):
    presets = [{"name": "Чат", "x1": 10, "y1": 20, "x2": 610, "y2": 220, "hotkey": None}]

    def setUp(self):
        config_manager._cache = dict(config_manager.DEFAULTS)
        self.addCleanup(setattr, config_manager, "_cache", None)
        for patcher in (
            mock.patch.object(main_window, "_UpdateCheckWorker", _IdleWorker),
            mock.patch.object(config_manager, "set_value", side_effect=lambda key, value: None),
            mock.patch.object(config_manager, "save_config", side_effect=lambda cfg: None),
            mock.patch("settings.region_presets.load_presets", side_effect=lambda: list(self.presets)),
            mock.patch("audio.capture.list_loopback_devices", return_value=[]),
            mock.patch("audio.stt.resolve_model_dir", return_value="C:/models/whisper"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.home = self.window._home_page


class TestTabs(_WindowCase):
    def test_feature_tabs_come_before_options_and_history(self):
        rail = self.window._btn_home.parentWidget().layout()
        order = [rail.itemAt(i).widget() for i in range(rail.count()) if rail.itemAt(i).widget() is not None]
        buttons = [w for w in order if w in self.window._nav_buttons]
        self.assertEqual(
            buttons,
            [
                self.window._btn_home,
                self.window._btn_subtitles,
                self.window._btn_monitoring,
                self.window._btn_settings,
                self.window._btn_history,
            ],
        )

    def test_rail_buttons_open_their_pages(self):
        for button, page in (
            (self.window._btn_subtitles, MainWindow.PAGE_SUBTITLES),
            (self.window._btn_monitoring, MainWindow.PAGE_MONITORING),
            (self.window._btn_home, MainWindow.PAGE_HOME),
        ):
            button.click()
            self.assertEqual(self.window._stack.currentIndex(), page)
            self.assertTrue(button.isChecked())
            self.assertEqual(sum(b.isChecked() for b in self.window._nav_buttons), 1)


class TestHomeSwitches(_WindowCase):
    def test_subtitles_switch_asks_to_start_and_stop(self):
        asked = []
        self.window.subtitles_toggle_requested.connect(asked.append)
        self.home._sw_subtitles.setChecked(True)
        self.home._sw_subtitles.setChecked(False)
        self.assertEqual(asked, [True, False])

    def test_switches_follow_the_real_state_without_asking_again(self):
        asked = []
        self.window.subtitles_toggle_requested.connect(asked.append)
        self.window.monitor_region_requested.connect(lambda *box: asked.append(box))
        self.window.stop_monitoring_requested.connect(lambda: asked.append("stop"))
        self.window.set_subtitles_active(True)  # e.g. started from the tray
        self.window.set_monitoring_active(True)
        self.assertTrue(self.home._sw_subtitles.isChecked())
        self.assertTrue(self.home._sw_monitoring.isChecked())
        self.window.set_subtitles_active(False)  # e.g. the model failed to load
        self.window.set_monitoring_active(False)
        self.assertFalse(self.home._sw_subtitles.isChecked())
        self.assertFalse(self.home._sw_monitoring.isChecked())
        self.assertEqual(asked, [])

    def test_monitoring_switch_starts_the_selected_region_and_stops(self):
        start, stop = mock.Mock(), mock.Mock()
        self.window.monitor_region_requested.connect(start)
        self.window.stop_monitoring_requested.connect(stop)
        self.home._sw_monitoring.setChecked(True)
        start.assert_called_once_with(10, 20, 610, 220)
        self.home._sw_monitoring.setChecked(False)
        stop.assert_called_once()

    def test_monitoring_switch_without_regions_opens_the_tab(self):
        self.presets = []
        start = mock.Mock()
        self.window.monitor_region_requested.connect(start)
        self.home._sw_monitoring.setChecked(True)
        start.assert_not_called()
        self.assertFalse(self.home._sw_monitoring.isChecked())
        self.assertEqual(self.window._stack.currentIndex(), MainWindow.PAGE_MONITORING)


class TestScreenChange(_WindowCase):
    def test_crossing_to_another_monitor_recalculates_the_frame(self):
        if not self.window._custom_frame:
            self.skipTest("custom frame is Windows-only")
        with mock.patch.object(main_window.title_bar, "refresh_frame") as refresh:
            self.window.windowHandle().screenChanged.emit(QApplication.primaryScreen())
        refresh.assert_called_once_with(self.window)


class TestLinksToSettings(_WindowCase):
    def test_tabs_lead_to_their_settings_sections(self):
        with mock.patch.object(self.window, "show_settings_section") as show:
            self.window._subtitles_page._btn_settings.click()
            self.window._monitoring_page._btn_settings.click()
        self.assertEqual([call.args[0] for call in show.call_args_list], ["subtitles", "regions"])


if __name__ == "__main__":
    unittest.main()
