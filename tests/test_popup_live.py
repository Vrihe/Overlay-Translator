"""
tests/test_popup_live.py — the result popup during live monitoring: it is kept out of
screen captures (so monitoring and OCR never see it), stays opaque (the exclusion
fails on translucent windows), and a live update does not take the keyboard focus.
Also the region presets dialog: the monitoring button and the list rows.

Widgets are built offscreen; the Windows API call is mocked.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from ui import result_popup
from ui.result_popup import ResultPopup, show_result

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class TestCaptureExclusion(unittest.TestCase):
    def setUp(self):
        self.popup = ResultPopup("src", "перевод")
        self.addCleanup(self.popup.deleteLater)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_shown_popup_is_excluded_from_capture(self):
        with mock.patch.object(result_popup.ctypes, "windll") as windll:
            self.popup.show()
        windll.user32.SetWindowDisplayAffinity.assert_called_once_with(int(self.popup.winId()), 0x11)

    def test_popup_is_opaque(self):
        # SetWindowDisplayAffinity fails on WA_TranslucentBackground (layered) windows.
        self.assertFalse(self.popup.testAttribute(Qt.WA_TranslucentBackground))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_api_failure_is_harmless(self):
        with mock.patch.object(result_popup.ctypes, "windll") as windll:
            windll.user32.SetWindowDisplayAffinity.side_effect = OSError("old Windows")
            self.popup._exclude_from_capture()  # must not raise
        windll.user32.SetWindowDisplayAffinity.assert_called_once()


class TestLiveUpdate(unittest.TestCase):
    def setUp(self):
        self.popup = ResultPopup(is_loading=True)
        self.addCleanup(self.popup.deleteLater)

    def test_live_update_keeps_the_focus_elsewhere(self):
        with (
            mock.patch.object(self.popup, "activateWindow") as activate,
            mock.patch.object(self.popup, "raise_") as raise_,
        ):
            self.popup.update_content("src", "new", activate=False)
        activate.assert_not_called()
        raise_.assert_called_once()
        self.assertEqual(self.popup._translated, "new")

    def test_normal_update_activates(self):
        with mock.patch.object(self.popup, "activateWindow") as activate:
            self.popup.update_content("src", "new")
        activate.assert_called_once()

    def test_show_result_passes_activate_to_the_open_popup(self):
        with (
            mock.patch.object(self.popup, "update_content") as update,
            mock.patch.object(type(result_popup.config), "NOTIFICATION_TYPE", "popup", create=True),
        ):
            same = show_result("src", "t", existing_popup=self.popup, activate=False)
        self.assertIs(same, self.popup)
        self.assertFalse(update.call_args.kwargs["activate"])


class TestStopMonitoringButton(unittest.TestCase):
    def setUp(self):
        self.popup = ResultPopup("src", "перевод")
        self.addCleanup(self.popup.deleteLater)

    def test_hidden_unless_monitoring(self):
        self.assertTrue(self.popup._btn_stop_monitoring.isHidden())
        self.popup.set_monitoring(True)
        self.assertFalse(self.popup._btn_stop_monitoring.isHidden())

    def test_click_asks_to_stop_and_hides_the_button(self):
        stop = mock.Mock()
        self.popup.stop_monitoring_clicked.connect(stop)
        self.popup.set_monitoring(True)
        self.popup._btn_stop_monitoring.click()
        stop.assert_called_once()
        self.assertTrue(self.popup._btn_stop_monitoring.isHidden())

    def test_kept_across_live_updates(self):
        self.popup.set_monitoring(True)
        self.popup.update_content("src", "новый текст", activate=False)
        self.assertFalse(self.popup._btn_stop_monitoring.isHidden())


class TestScrollKeptOnLiveUpdates(unittest.TestCase):
    LONG = "\n".join(f"line {i} of a long chat translation" for i in range(80))

    def _update(self, popup, text):
        popup.update_content("src", text, activate=False)
        _APP.processEvents()  # the restore runs after the rebuilt layout settles
        return popup._scroll_area.verticalScrollBar()

    def _shown(self, *args, **kwargs):
        popup = ResultPopup(*args, **kwargs)
        self.addCleanup(popup.deleteLater)
        popup.show()
        _APP.processEvents()
        return popup

    def test_middle_position_is_kept(self):
        popup = self._shown("src", self.LONG)
        bar = popup._scroll_area.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum() // 2)
        middle = bar.value()
        self.assertEqual(self._update(popup, self.LONG + "\nnew line").value(), middle)

    def test_bottom_follows_new_lines(self):
        popup = self._shown("src", self.LONG)
        bar = popup._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        bar = self._update(popup, self.LONG + "\nnew\nlines")
        self.assertEqual(bar.value(), bar.maximum())

    def test_first_result_starts_at_the_top(self):
        popup = self._shown(is_loading=True)
        bar = self._update(popup, self.LONG)
        self.assertEqual(bar.value(), 0)


class TestRegionPresetsDialog(unittest.TestCase):
    presets = [
        {"id": "a", "name": "Twitch чат", "x1": 10, "y1": 20, "x2": 610, "y2": 820, "hotkey": "ctrl+alt+1"},
        {"id": "b", "name": "Квесты", "x1": 0, "y1": 0, "x2": 300, "y2": 100, "hotkey": None},
    ]

    def setUp(self):
        patcher = mock.patch("ui.region_presets_dialog.load_presets", return_value=list(self.presets))
        patcher.start()
        self.addCleanup(patcher.stop)
        from ui.region_presets_dialog import RegionPresetsDialog

        self.dialog = RegionPresetsDialog()
        self.addCleanup(self.dialog.deleteLater)

    def test_rows_are_short_with_coordinates_in_the_tooltip(self):
        first = self.dialog._list.item(0)
        self.assertEqual(first.text(), "Twitch чат   ·   600×800   ·   CTRL+ALT+1")
        self.assertEqual(first.toolTip(), "(10, 20) → (610, 820)")
        self.assertIn("без бинда", self.dialog._list.item(1).text())

    def test_monitoring_is_started_from_the_settings_not_here(self):
        self.assertFalse(hasattr(self.dialog, "_btn_monitor"))
        self.assertFalse(hasattr(self.dialog, "preset_monitor"))


if __name__ == "__main__":
    unittest.main()
