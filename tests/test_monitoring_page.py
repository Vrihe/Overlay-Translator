"""
tests/test_monitoring_page.py — the Monitoring tab: the list of saved regions with their
binds, the add / manage buttons and the start / stop button of live monitoring.

The page is built offscreen; the region presets and settings.json are faked.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

from settings import config_manager

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class _PageCase(unittest.TestCase):
    presets = [
        {"name": "Чат", "x1": 10, "y1": 20, "x2": 610, "y2": 220, "hotkey": "ctrl+alt+1"},
        {"name": "Квесты", "x1": 0, "y1": 0, "x2": 300, "y2": 100, "hotkey": None},
    ]

    def setUp(self):
        config_manager._cache = {**config_manager.DEFAULTS, "live_interval_sec": 7}
        self.addCleanup(setattr, config_manager, "_cache", None)
        patcher = mock.patch("settings.region_presets.load_presets", side_effect=lambda: list(self.presets))
        patcher.start()
        self.addCleanup(patcher.stop)
        from ui.monitoring_page import MonitoringPage

        self.page = MonitoringPage()
        self.addCleanup(self.page.deleteLater)

    def _rows(self):
        lst = self.page._regions_list
        return [lst.item(i).text() for i in range(lst.count())]


class TestRegions(_PageCase):
    def test_lists_regions_with_size_and_bind(self):
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertIn("Чат", rows[0])
        self.assertIn("600×200", rows[0])
        self.assertIn("CTRL+ALT+1", rows[0])
        self.assertIn("без бинда", rows[1])

    def test_empty_state(self):
        self.presets = []
        self.page.refresh_regions()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIn("Добавить регион", rows[0])
        self.assertFalse(self.page._btn_monitor.isEnabled())  # nothing to monitor

    def test_reload_picks_up_new_regions(self):
        self.presets = [*self.presets, {"name": "Карта", "x1": 0, "y1": 0, "x2": 50, "y2": 50}]
        self.page.reload()
        self.assertEqual(len(self._rows()), 3)

    def test_buttons_ask_main_to_act(self):
        add, manage, settings = mock.Mock(), mock.Mock(), mock.Mock()
        self.page.add_region_requested.connect(add)
        self.page.manage_regions_requested.connect(manage)
        self.page.open_settings_requested.connect(settings)
        self.page._btn_add.click()
        self.page._btn_manage.click()
        self.page._btn_settings.click()
        add.assert_called_once()
        manage.assert_called_once()
        settings.assert_called_once()

    def test_saved_interval_is_shown(self):
        self.assertIn("7", self.page._params_label.text())


class TestMonitoring(_PageCase):
    def test_button_starts_the_selected_region(self):
        start = mock.Mock()
        self.page.monitor_region_requested.connect(start)
        self.page._regions_list.setCurrentRow(1)
        self.assertEqual(self.page._btn_monitor.text(), "ЗАПУСТИТЬ МОНИТОРИНГ")
        self.page._btn_monitor.click()
        start.assert_called_once_with(0, 0, 300, 100)

    def test_while_monitoring_the_button_stops_it(self):
        stop, start = mock.Mock(), mock.Mock()
        self.page.stop_monitoring_requested.connect(stop)
        self.page.monitor_region_requested.connect(start)
        self.assertTrue(self.page._status.isHidden())
        self.page.set_monitoring_active(True)
        self.assertEqual(self.page._btn_monitor.text(), "ОСТАНОВИТЬ МОНИТОРИНГ")
        self.assertFalse(self.page._status.isHidden())
        self.page._btn_monitor.click()
        stop.assert_called_once()
        start.assert_not_called()
        self.page.set_monitoring_active(False)
        self.assertEqual(self.page._btn_monitor.text(), "ЗАПУСТИТЬ МОНИТОРИНГ")
        self.assertTrue(self.page._status.isHidden())

    def test_monitoring_started_elsewhere_can_be_stopped_without_regions(self):
        self.presets = []
        self.page.refresh_regions()
        self.page.set_monitoring_active(True)  # e.g. from the tray, for a one-off area
        self.assertTrue(self.page._btn_monitor.isEnabled())


if __name__ == "__main__":
    unittest.main()
