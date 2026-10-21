"""
tests/test_settings_regions.py — Settings → Regions: the list of saved regions with
their binds, the add / manage buttons, and the live monitoring interval and
sensitivity, plus how LiveMonitor applies them.

The settings page is built offscreen with everything mocked (settings_widget_case).
"""

import unittest
from unittest import mock

from capture.live_monitor import (
    MAX_INTERVAL_SEC, MIN_INTERVAL_SEC, SENSITIVITY_THRESHOLDS, LiveMonitor, threshold_for,
)
from tests.settings_widget_case import SettingsWidgetCase


def setUpModule():
    import i18n
    i18n.set_language("ru")


def tearDownModule():
    import i18n
    i18n.set_language(None)


class TestLiveMonitorSettings(unittest.TestCase):

    def test_sensitivity_thresholds(self):
        self.assertLess(threshold_for("high"), threshold_for("medium"))
        self.assertLess(threshold_for("medium"), threshold_for("low"))
        self.assertEqual(threshold_for("medium"), 2.5)  # the tested default stays
        self.assertEqual(threshold_for("nonsense"), threshold_for("medium"))
        self.assertEqual(threshold_for(None), threshold_for("medium"))

    def test_interval_is_clamped(self):
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=0).interval_sec, MIN_INTERVAL_SEC)
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=9999).interval_sec, MAX_INTERVAL_SEC)
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=7).interval_sec, 7)

    def test_monitor_keeps_its_threshold(self):
        monitor = LiveMonitor(0, 0, 10, 10, threshold=SENSITIVITY_THRESHOLDS["low"])
        self.assertEqual(monitor.threshold, 5.0)


class TestRegionsPage(SettingsWidgetCase):

    presets = [
        {"name": "Чат", "x1": 10, "y1": 20, "x2": 610, "y2": 220, "hotkey": "ctrl+alt+1"},
        {"name": "Квесты", "x1": 0, "y1": 0, "x2": 300, "y2": 100, "hotkey": None},
    ]

    def _rows(self):
        lst = self.widget._regions_list
        return [lst.item(i).text() for i in range(lst.count())]

    def test_lists_regions_with_size_and_bind(self):
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertIn("Чат", rows[0])
        self.assertIn("600×200", rows[0])
        self.assertIn("CTRL+ALT+1", rows[0])
        self.assertIn("без бинда", rows[1])

    def test_empty_state(self):
        self.presets = []
        self.widget.refresh_regions()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIn("Добавить регион", rows[0])

    def test_buttons_ask_main_to_act(self):
        add, manage = mock.Mock(), mock.Mock()
        self.widget.add_region_requested.connect(add)
        self.widget.manage_regions_requested.connect(manage)
        self.widget._btn_add_region.click()
        self.widget._btn_manage_regions.click()
        add.assert_called_once()
        manage.assert_called_once()

    def test_live_settings_load_and_autosave(self):
        self.assertEqual(self.widget._live_interval_spin.value(), 10)
        self.assertEqual(self.widget._live_sensitivity_combo.currentData(), "medium")
        self.widget._live_interval_spin.setValue(25)
        index = self.widget._live_sensitivity_combo.findData("high")
        self.widget._live_sensitivity_combo.setCurrentIndex(index)
        self.widget._flush_autosave()
        self.assertEqual(self.disk["live_interval_sec"], 25)
        self.assertEqual(self.disk["live_sensitivity"], "high")


if __name__ == "__main__":
    unittest.main()
