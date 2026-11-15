"""
tests/test_settings_popup_behavior.py — Settings → Popup → "Ненавязчивость": the opacity
slider, the compact switch and the click-through switch save themselves, and the mouse
wheel over the slider scrolls the page instead of changing it.

The settings page is built offscreen with everything mocked (settings_widget_case).
"""

import unittest
from unittest import mock

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent

from settings import config_manager
from tests.settings_widget_case import SettingsWidgetCase
from ui import overlay_behavior
from ui.wheel_guard import _WheelGuard


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class TestPopupBehaviorSettings(SettingsWidgetCase):
    def test_defaults_keep_the_old_look(self):
        self.assertEqual(config_manager.DEFAULTS["popup_opacity"], 100)
        self.assertFalse(config_manager.DEFAULTS["popup_compact"])
        self.assertFalse(config_manager.DEFAULTS["popup_click_through"])

    def test_form_shows_the_saved_values(self):
        slider = self.widget._opacity_slider
        self.assertEqual((slider.minimum(), slider.maximum()), (overlay_behavior.MIN_OPACITY, 100))
        self.assertEqual(slider.value(), 100)
        self.assertEqual(self.widget._opacity_value.text(), "100 %")
        self.assertFalse(self.widget._chk_popup_compact.isChecked())
        self.assertFalse(self.widget._chk_click_through.isChecked())

    def test_changes_are_autosaved(self):
        self.widget._opacity_slider.setValue(65)
        self.assertEqual(self.widget._opacity_value.text(), "65 %")
        self.widget._chk_popup_compact.setChecked(True)
        self.widget._chk_click_through.setChecked(True)
        self.widget._flush_autosave()
        self.assertEqual(self.disk["popup_opacity"], 65)
        self.assertTrue(self.disk["popup_compact"])
        self.assertTrue(self.disk["popup_click_through"])

    def test_saved_values_reach_the_overlays(self):
        self.widget._opacity_slider.setValue(65)
        self.widget._chk_click_through.setChecked(True)
        self.widget._flush_autosave()
        self.assertAlmostEqual(overlay_behavior.rest_opacity(), 0.65)
        self.assertTrue(overlay_behavior.click_through())

    def test_a_broken_saved_value_does_not_break_the_page(self):
        self.disk["popup_opacity"] = "junk"
        config_manager._cache = dict(self.disk)
        self.widget.reload()
        self.assertEqual(self.widget._opacity_slider.value(), 100)

    def test_wheel_over_the_slider_does_not_change_it(self):
        slider = self.widget._opacity_slider
        slider.setValue(70)
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
        self.assertEqual(event.type(), QEvent.Wheel)
        with mock.patch("ui.wheel_guard.QCoreApplication.sendEvent"):
            self.assertTrue(_WheelGuard().eventFilter(slider, event))  # swallowed: the page scrolls instead
        self.assertEqual(slider.value(), 70)


if __name__ == "__main__":
    unittest.main()
