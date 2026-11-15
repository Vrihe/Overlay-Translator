"""
tests/test_settings_regions.py — Settings → Monitoring: the live monitoring interval and
sensitivity, plus how LiveMonitor applies them. (The list of regions and the start button
are on the main window's Monitoring tab: tests/test_monitoring_page.py.)

The settings page is built offscreen with everything mocked (settings_widget_case).
"""

import unittest

from capture.live_monitor import (
    MAX_INTERVAL_SEC,
    MIN_INTERVAL_SEC,
    SENSITIVITY_THRESHOLDS,
    LiveMonitor,
    threshold_for,
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
        self.assertEqual(threshold_for("medium"), 0.25)  # percent of changed cells
        self.assertEqual(threshold_for("nonsense"), threshold_for("medium"))
        self.assertEqual(threshold_for(None), threshold_for("medium"))

    def test_interval_is_clamped(self):
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=0).interval_sec, MIN_INTERVAL_SEC)
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=9999).interval_sec, MAX_INTERVAL_SEC)
        self.assertEqual(LiveMonitor(0, 0, 10, 10, interval_sec=7).interval_sec, 7)

    def test_monitor_keeps_its_threshold(self):
        monitor = LiveMonitor(0, 0, 10, 10, threshold=SENSITIVITY_THRESHOLDS["low"])
        self.assertEqual(monitor.threshold, 0.6)


class TestMonitoringSettings(SettingsWidgetCase):
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
