"""
tests/test_live_monitoring.py — live monitoring of a chat region: the change detector
fires on one new chat line (it never did with the old 64×64 mean metric) but not on a
blinking cursor, its popup stays open while monitoring with "keep open" on, and a
restarted monitor shows the region's whole text again.

Frames are drawn with synthetic text; widgets are offscreen; no OCR, no capture.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFont
from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QApplication

import config
from capture.live_monitor import LiveMonitor, threshold_for
from tests.settings_widget_case import SettingsWidgetCase
from translate.line_feed import RegionFeed
from ui.result_popup import ResultPopup

_APP = QApplication.instance() or QApplication(sys.argv[:1])
_FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"
_W, _H, _LINE = 320, 726, 20
_BG, _FG = (20, 22, 28), (225, 225, 225)


def _chat(lines: int) -> Image.Image:
    """A dark chat panel with *lines* synthetic messages from the top."""
    font = ImageFont.truetype(str(_FONT), 13)
    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img)
    for row in range(lines):
        draw.text((6, 4 + row * _LINE), f"player{row}: synthetic message {row}", fill=_FG, font=font)
    return img


def _diff(a: Image.Image, b: Image.Image) -> float:
    return LiveMonitor._signature_diff(LiveMonitor._compute_signature(a), LiveMonitor._compute_signature(b))


class TestChangeDetection(unittest.TestCase):
    def test_one_new_chat_line_is_a_change_at_every_sensitivity(self):
        change = _diff(_chat(5), _chat(6))
        for sensitivity in ("high", "medium", "low"):
            self.assertGreater(change, threshold_for(sensitivity), sensitivity)

    def test_a_blinking_cursor_is_not(self):
        frame = _chat(10)
        blink = frame.copy()
        ImageDraw.Draw(blink).rectangle((300, 700, 301, 713), fill=_FG)
        self.assertLess(_diff(frame, blink), threshold_for("high"))

    def test_identical_frames_do_not_differ(self):
        frame = _chat(10)
        self.assertEqual(_diff(frame, frame.copy()), 0.0)

    def test_signature_keeps_the_aspect_ratio(self):
        self.assertEqual(len(LiveMonitor._compute_signature(_chat(1))), (_W // 3) * (_H // 3))


class TestMonitoringPopupStaysOpen(unittest.TestCase):
    def setUp(self):
        self.popup = ResultPopup("s", "перевод")
        self.addCleanup(self.popup.deleteLater)
        self.popup._start_auto_timer()

    def _keep_open(self, value):
        patcher = mock.patch.object(
            type(config), "LIVE_POPUP_KEEP_OPEN", new_callable=mock.PropertyMock, return_value=value
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_auto_hide_while_monitoring(self):
        self._keep_open(True)
        self.popup.set_monitoring(True)
        self.assertFalse(self.popup._auto_timer.isActive())
        self.popup.update_content("s", "новое")  # a live update must not re-arm it
        self.assertFalse(self.popup._auto_timer.isActive())

    def test_auto_hide_resumes_when_monitoring_stops(self):
        self._keep_open(True)
        self.popup.set_monitoring(True)
        self.popup.set_monitoring(False)
        self.assertTrue(self.popup._auto_timer.isActive())

    def test_option_off_keeps_the_usual_timer(self):
        self._keep_open(False)
        self.popup.set_monitoring(True)
        self.assertTrue(self.popup._auto_timer.isActive())


class TestMonitorRestart(unittest.TestCase):
    def test_starting_a_monitor_forgets_the_region_feed(self):
        from tests.main_import import import_main

        main = import_main()
        app = mock.Mock()
        app._live_monitor = None
        app._tray = None
        key = main._anchor_key(QRect(10, 20, 300, 400))
        other = (0, 0, 5, 5)
        app._feeds = {key: RegionFeed(), other: RegionFeed()}
        with mock.patch("capture.live_monitor.LiveMonitor"):
            main.TranslatorApp._start_live_monitoring(app, 10, 20, 310, 420)
        self.assertNotIn(key, app._feeds)  # the first check shows the whole region again
        self.assertIn(other, app._feeds)


class TestKeepOpenSetting(SettingsWidgetCase):
    def test_switch_loads_and_saves(self):
        self.assertTrue(self.widget._chk_live_keep_open.isChecked())  # default: keep open
        self.widget._chk_live_keep_open.setChecked(False)
        self.widget._flush_autosave()
        self.assertFalse(self.disk["live_popup_keep_open"])


if __name__ == "__main__":
    unittest.main()
