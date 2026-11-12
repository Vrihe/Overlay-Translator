"""
tests/test_overlay_behavior.py — ui/overlay_behavior.py and what the result popup and
the subtitle strip do with it: opacity at rest and when engaged, click-through with
Alt, the compact header and the frame colour.

The cursor, the Alt key and the Win32 calls are mocked; settings come from a fake
settings.json in memory.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QSlider, QWidget

from settings import config_manager
from ui import overlay_behavior, theme
from ui.overlay_behavior import EngageWatcher
from ui.result_popup import ResultPopup
from ui.subtitle_window import SubtitleWindow

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class _OverlayCase(unittest.TestCase):
    settings: dict = {}

    def setUp(self):
        self.disk = {**config_manager.DEFAULTS, "popup_size": None, "subtitles_pos": None, **self.settings}
        config_manager._cache = dict(self.disk)
        self.addCleanup(setattr, config_manager, "_cache", None)
        self.inside = False
        self.alt = False
        self.buttons = Qt.NoButton

        def fake_set(key, value):
            self.disk[key] = value
            config_manager._cache = dict(self.disk)

        for patcher in (
            mock.patch.object(config_manager, "set_value", side_effect=fake_set),
            mock.patch.object(EngageWatcher, "_cursor_inside", lambda _self: self.inside),
            mock.patch.object(overlay_behavior, "alt_down", lambda: self.alt),
            mock.patch.object(overlay_behavior.QApplication, "mouseButtons", lambda: self.buttons),
            mock.patch.object(overlay_behavior, "set_click_through"),
            mock.patch.object(overlay_behavior, "exclude_from_capture"),
            mock.patch.object(ResultPopup, "_exclude_from_capture"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.click_through = overlay_behavior.set_click_through

    def set(self, **values):
        self.disk.update(values)
        config_manager._cache = dict(self.disk)

    def popup(self, **kwargs):
        popup = ResultPopup("src", "перевод", **kwargs)
        self.addCleanup(popup.deleteLater)
        self.addCleanup(popup.hide)
        popup.show()
        return popup


class TestSettingsValues(_OverlayCase):
    def test_defaults_change_nothing(self):
        self.assertEqual(overlay_behavior.rest_opacity(), 1.0)
        self.assertFalse(overlay_behavior.compact())
        self.assertFalse(overlay_behavior.click_through())

    def test_opacity_is_clamped(self):
        for saved, expected in ((70, 0.7), (5, 0.4), (250, 1.0), ("junk", 1.0), (None, 1.0)):
            self.set(popup_opacity=saved)
            self.assertAlmostEqual(overlay_behavior.rest_opacity(), expected)

    def test_click_through_keeps_the_window_layered(self):
        # Qt removes WS_EX_LAYERED at opacity 1.0, and click-through needs it.
        self.set(popup_click_through=True, popup_opacity=100)
        self.assertLess(overlay_behavior.rest_opacity(), 1.0)


class TestEngageWatcher(_OverlayCase):
    settings = {"popup_opacity": 60}

    def setUp(self):
        super().setUp()
        self.widget = QWidget()
        self.addCleanup(self.widget.deleteLater)
        self.changes = []
        self.watcher = EngageWatcher(self.widget, self.changes.append)

    def test_translucent_at_rest_and_solid_under_the_cursor(self):
        self.watcher.poll()
        self.assertAlmostEqual(self.widget.windowOpacity(), 0.6, places=2)
        self.inside = True
        self.watcher.poll()
        self.assertEqual(self.widget.windowOpacity(), 1.0)
        self.assertTrue(self.watcher.engaged)
        self.inside = False
        self.watcher.poll()
        self.assertAlmostEqual(self.widget.windowOpacity(), 0.6, places=2)
        self.assertEqual(self.changes, [False, True, False])

    def test_nothing_is_reapplied_while_nothing_changes(self):
        self.watcher.poll()
        self.watcher.poll()
        self.assertEqual(self.changes, [False])
        self.assertEqual(self.click_through.call_count, 1)

    def test_a_pressed_button_keeps_it_engaged_outside_the_window(self):
        self.inside = True
        self.watcher.poll()
        self.inside, self.buttons = False, Qt.LeftButton  # resizing: the cursor left the edge
        self.watcher.poll()
        self.assertTrue(self.watcher.engaged)
        self.buttons = Qt.NoButton
        self.watcher.poll()
        self.assertFalse(self.watcher.engaged)

    def test_a_button_pressed_elsewhere_does_not_engage(self):
        self.buttons = Qt.LeftButton
        self.watcher.poll()
        self.assertFalse(self.watcher.engaged)

    def test_a_settings_change_applies_to_an_open_overlay(self):
        self.watcher.poll()
        self.set(popup_opacity=80)
        self.watcher.poll()
        self.assertAlmostEqual(self.widget.windowOpacity(), 0.8, places=2)

    def test_click_through_needs_alt_over_the_window(self):
        self.set(popup_click_through=True)
        self.inside = True
        self.watcher.poll()
        self.assertFalse(self.watcher.engaged)  # the cursor alone no longer engages
        self.click_through.assert_called_with(self.widget, True)
        self.alt = True
        self.watcher.poll()
        self.assertTrue(self.watcher.engaged)
        self.click_through.assert_called_with(self.widget, False)  # clickable while Alt is held
        self.assertEqual(self.widget.windowOpacity(), 1.0)
        self.alt = False
        self.watcher.poll()
        self.click_through.assert_called_with(self.widget, True)

    def test_alt_away_from_the_window_does_nothing(self):
        self.set(popup_click_through=True)
        self.alt = True
        self.watcher.poll()
        self.assertFalse(self.watcher.engaged)

    def test_restart_reapplies_the_window_styles(self):
        self.set(popup_click_through=True)
        self.watcher.start()
        self.watcher.stop()
        self.watcher.start()  # a hidden and re-shown window lost its ex-style
        self.addCleanup(self.watcher.stop)
        self.assertEqual(self.click_through.call_count, 2)


class TestPopupAtRest(_OverlayCase):
    settings = {"popup_opacity": 70}

    def test_shown_translucent_and_solid_when_engaged(self):
        popup = self.popup()
        self.assertAlmostEqual(popup.windowOpacity(), 0.7, places=2)
        self.inside = True
        popup._watcher.poll()
        self.assertEqual(popup.windowOpacity(), 1.0)

    def test_frame_is_accent_only_when_fresh_or_engaged(self):
        popup = self.popup()
        self.assertEqual(self.frame(popup), theme.qcolor("accent").name())  # a new result
        popup._fresh_timer.timeout.emit()
        self.assertEqual(self.frame(popup), theme.qcolor("dim").name())
        self.inside = True
        popup._watcher.poll()
        self.assertEqual(self.frame(popup), theme.qcolor("accent").name())

    def test_an_update_is_fresh_again(self):
        popup = self.popup()
        popup._fresh_timer.timeout.emit()
        popup.update_content("src", "новый перевод")
        self.assertEqual(self.frame(popup), theme.qcolor("accent").name())

    def test_error_frame_stays_red(self):
        popup = self.popup(is_error=True)
        popup._fresh_timer.timeout.emit()
        self.assertEqual(self.frame(popup), theme.qcolor("error").name())

    def test_the_fade_out_is_not_fought(self):
        popup = self.popup()
        popup._fade_out_and_close()
        self.assertFalse(popup._watcher._timer.isActive())

    def test_header_is_always_there_without_compact_mode(self):
        popup = self.popup()
        self.assertFalse(popup._header.isHidden())

    @staticmethod
    def frame(popup) -> str:
        return popup.grab().toImage().pixelColor(0, 0).name()


class TestFitToText(_OverlayCase):
    """Without a saved size the popup is exactly as tall as its wrapped text."""

    LONG = "Босс уязвим к холоду, держитесь слева и не стойте в лужах. " * 6

    def chrome(self, popup) -> int:
        margins = popup._card.layout().contentsMargins()
        return margins.top() + margins.bottom() + popup._header_delta()

    def text_height(self, popup) -> int:
        margins = popup._card.layout().contentsMargins()
        return popup._scroll_area.widget().heightForWidth(popup.width() - margins.left() - margins.right())

    def test_short_text_leaves_no_empty_space(self):
        popup = self.popup()
        self.assertEqual(popup.height(), self.chrome(popup) + self.text_height(popup))
        self.assertLess(popup.height(), 100)

    def test_long_text_grows_the_popup(self):
        short = self.popup()
        long = ResultPopup("src", self.LONG)
        self.addCleanup(long.deleteLater)
        self.assertGreater(long.height(), short.height())
        self.assertEqual(long.height(), self.chrome(long) + self.text_height(long))

    def test_an_update_with_less_text_shrinks_it(self):
        popup = ResultPopup("src", self.LONG)
        self.addCleanup(popup.deleteLater)
        tall = popup.height()
        popup.update_content("src", "коротко")
        self.assertLess(popup.height(), tall)

    def test_height_is_capped_and_the_rest_scrolls(self):
        popup = ResultPopup("src", self.LONG * 20)
        self.addCleanup(popup.deleteLater)
        self.assertEqual(popup.height(), ResultPopup._MAX_HEIGHT)

    def test_loading_popup_is_just_its_header(self):
        popup = ResultPopup(is_loading=True)
        self.addCleanup(popup.deleteLater)
        self.assertEqual(popup.height(), self.chrome(popup))

    def test_saved_size_wins_over_the_fit(self):
        self.set(popup_size=[420, 300])
        popup = self.popup()
        self.assertEqual((popup.width(), popup.height()), (420, 300))


class TestCompactPopup(_OverlayCase):
    settings = {"popup_compact": True}

    def test_header_shows_only_while_engaged_and_the_text_stays_put(self):
        popup = self.popup()
        self.assertTrue(popup._header.isHidden())
        rest = popup.geometry()
        self.inside = True
        popup._watcher.poll()
        self.assertFalse(popup._header.isHidden())
        grown = popup.geometry()
        self.assertGreater(grown.height(), rest.height())
        self.assertEqual(grown.bottom(), rest.bottom())  # it grew upwards
        self.inside = False
        popup._watcher.poll()
        self.assertTrue(popup._header.isHidden())
        self.assertEqual(popup.geometry(), rest)

    def test_compact_popup_is_smaller_than_a_normal_one(self):
        compact = self.popup()
        self.set(popup_compact=False)
        normal = self.popup()
        self.assertLess(compact.height(), normal.height())

    def test_loading_popup_keeps_its_header(self):
        popup = ResultPopup(is_loading=True)
        self.addCleanup(popup.deleteLater)
        self.assertFalse(popup._header.isHidden())  # "Переводим…" is all it shows
        popup.update_content("src", "перевод")
        self.assertTrue(popup._header.isHidden())

    def test_update_while_engaged_keeps_the_header(self):
        popup = self.popup()
        self.inside = True
        popup._watcher.poll()
        popup.update_content("src", "новый перевод")
        self.assertFalse(popup._header.isHidden())
        self.inside = False
        popup._watcher.poll()
        self.assertTrue(popup._header.isHidden())

    def test_turning_compact_off_brings_the_header_back(self):
        popup = self.popup()
        self.set(popup_compact=False)
        popup._watcher.poll()
        self.assertFalse(popup._header.isHidden())

    def test_resize_saves_the_size_at_rest(self):
        popup = self.popup()
        self.inside = True
        popup._watcher.poll()  # resizing is only possible with the header on screen
        popup.resize(420, 200)
        popup._resized = True
        popup._finish_resize()
        self.assertEqual(self.disk["popup_size"], [420, 200 - popup._header_delta()])

    def test_saved_size_is_the_rest_size(self):
        self.set(popup_size=[420, 200])
        popup = self.popup()
        self.assertEqual((popup.width(), popup.height()), (420, 200))
        self.inside = True
        popup._watcher.poll()
        self.assertEqual(popup.height(), 200 + popup._header_delta())


class TestSubtitleStrip(_OverlayCase):
    settings = {"popup_opacity": 50}

    def setUp(self):
        super().setUp()
        self.window = SubtitleWindow()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.hide)

    def test_strip_follows_the_same_opacity(self):
        self.window.add_line("фраза")
        self.assertAlmostEqual(self.window.windowOpacity(), 0.5, places=2)
        self.inside = True
        self.window._watcher.poll()
        self.assertEqual(self.window.windowOpacity(), 1.0)

    def test_strip_is_click_through_too_and_reapplied_on_every_show(self):
        self.set(popup_click_through=True)
        self.window.add_line("фраза")
        self.click_through.assert_called_with(self.window, True)
        self.window.clear_lines()  # hides
        self.assertFalse(self.window._watcher._timer.isActive())
        self.click_through.reset_mock()
        self.window.add_line("ещё")
        self.click_through.assert_called_with(self.window, True)


class TestSliderStyle(unittest.TestCase):
    def test_slider_css_uses_the_palette(self):
        p = theme.current()
        css = theme.slider_css()
        self.assertIn(p.accent, css)
        slider = QSlider(Qt.Horizontal)
        self.addCleanup(slider.deleteLater)
        slider.setStyleSheet(css)  # must parse without warnings breaking the widget
        self.assertEqual(slider.orientation(), Qt.Horizontal)


if __name__ == "__main__":
    unittest.main()
