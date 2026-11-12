"""
tests/test_subtitle_window.py — ui/subtitle_window.py: the lines it keeps, when it
shows and hides, where it sits, and that it never takes the focus.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from settings import config_manager
from ui import subtitle_window
from ui.subtitle_window import SubtitleWindow

_APP = QApplication.instance() or QApplication(sys.argv[:1])


def _mouse(window, kind, local, button=Qt.LeftButton):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    position = QPointF(local)
    event = QMouseEvent(kind, position, QPointF(window.mapToGlobal(local)), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(window, event)


class _WindowCase(unittest.TestCase):
    saved_pos = None

    def setUp(self):
        self.disk = {**config_manager.DEFAULTS, "subtitles_pos": self.saved_pos}
        config_manager._cache = dict(self.disk)
        self.addCleanup(setattr, config_manager, "_cache", None)

        def fake_set(key, value):
            self.disk[key] = value
            config_manager._cache = dict(self.disk)

        for patcher in (
            mock.patch.object(config_manager, "set_value", side_effect=fake_set),
            mock.patch.object(SubtitleWindow, "_exclude_from_capture"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = SubtitleWindow()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.hide)


class TestInterimLine(_WindowCase):
    def test_interim_text_is_replaced_by_the_next_one_and_by_the_phrase(self):
        self.window.add_line("первая")
        self.window.set_partial("вторая фр")
        self.assertTrue(self.window._new_label.text().startswith("вторая фр"))
        self.assertEqual(self.window._old_label.text(), "первая")
        self.window.set_partial("вторая фраза по")
        self.assertEqual(self.window.partial_text(), "вторая фраза по")
        self.assertEqual(self.window.lines(), ["первая"])
        self.window.add_line("вторая фраза полностью")
        self.assertEqual(self.window.partial_text(), "")
        self.assertEqual(self.window._new_label.text(), "вторая фраза полностью")
        self.assertEqual(self.window._old_label.text(), "первая")

    def test_interim_text_alone_shows_the_strip_and_clearing_hides_it(self):
        self.window.set_partial("начало")
        self.assertTrue(self.window.isVisible())
        self.window.clear_lines()
        self.assertFalse(self.window.isVisible())


class TestSubtitleWindow(_WindowCase):
    def test_hidden_until_there_is_something_to_show(self):
        self.assertFalse(self.window.isVisible())
        self.window.add_line("первая фраза")
        self.assertTrue(self.window.isVisible())
        SubtitleWindow._exclude_from_capture.assert_called()

    def test_keeps_the_last_two_lines(self):
        for text in ("один", "два", "три"):
            self.window.add_line(text)
        self.assertEqual(self.window.lines(), ["два", "три"])
        self.assertEqual(self.window._new_label.text(), "три")
        self.assertEqual(self.window._old_label.text(), "два")

    def test_blank_text_is_ignored(self):
        self.window.add_line("   ")
        self.assertEqual(self.window.lines(), [])
        self.assertFalse(self.window.isVisible())

    def test_lines_expire_and_the_window_hides(self):
        self.window.add_line("фраза")
        self.assertTrue(self.window._line_timer.isActive())
        self.window._line_timer.timeout.emit()
        self.assertEqual(self.window.lines(), [])
        self.assertFalse(self.window.isVisible())

    def test_status_shows_the_window_and_times_out(self):
        self.window.set_status("Слушаю: Динамики", "ok")
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.status_text(), "Слушаю: Динамики")
        self.assertEqual(self.window._status_timer.remainingTime() > subtitle_window.STATUS_TTL_MS - 1000, True)
        self.window._status_timer.timeout.emit()
        self.assertFalse(self.window.isVisible())

    def test_errors_stay_longer(self):
        self.window.set_status("Модель не найдена", "error")
        self.assertGreater(self.window._status_timer.remainingTime(), subtitle_window.STATUS_TTL_MS)

    def test_status_expiry_keeps_the_subtitles(self):
        self.window.add_line("фраза")
        self.window.set_status("Слушаю", "ok")
        self.window.set_status("")
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.lines(), ["фраза"])

    def test_speech_is_shown_as_plain_text(self):
        self.window.add_line("<b>not bold</b>")
        self.assertEqual(self.window._new_label.textFormat(), Qt.PlainText)

    def test_never_takes_the_focus(self):
        flags = self.window.windowFlags()
        self.assertTrue(flags & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(flags & Qt.WindowStaysOnTopHint)
        self.assertTrue(self.window.testAttribute(Qt.WA_ShowWithoutActivating))

    def test_default_place_is_bottom_centre_and_growth_keeps_the_bottom(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.window.add_line("короткая")
        bottom = self.window.y() + self.window.height()
        centre = self.window.x() + self.window.width() // 2
        self.assertAlmostEqual(centre, screen.center().x(), delta=1)
        self.assertLess(bottom, screen.bottom())
        self.assertGreater(bottom, screen.center().y())
        height = self.window.height()
        self.window.add_line("вторая строка " * 30)
        self.assertGreater(self.window.height(), height)
        self.assertEqual(self.window.y() + self.window.height(), bottom)

    def test_drag_moves_it_and_saves_the_place(self):
        self.window.add_line("фраза")
        start = self.window.pos()
        _mouse(self.window, QEvent.MouseButtonPress, QPoint(10, 10))
        _mouse(self.window, QEvent.MouseMove, QPoint(60, -30), Qt.NoButton)
        _mouse(self.window, QEvent.MouseButtonRelease, QPoint(10, 10))
        self.assertNotEqual(self.window.pos(), start)
        saved = self.disk["subtitles_pos"]
        self.assertEqual(saved, [self.window.x() + self.window.width() // 2, self.window.y() + self.window.height()])
        # The next line stays where the user put the strip.
        self.window.add_line("ещё одна")
        self.assertEqual(self.window.y() + self.window.height(), saved[1])

    def test_click_without_a_move_saves_nothing(self):
        self.window.add_line("фраза")
        _mouse(self.window, QEvent.MouseButtonPress, QPoint(10, 10))
        _mouse(self.window, QEvent.MouseButtonRelease, QPoint(10, 10))
        self.assertIsNone(self.disk["subtitles_pos"])


class TestSavedPlace(_WindowCase):
    saved_pos = [400, 300]

    def test_saved_place_is_used(self):
        self.window.add_line("фраза")
        self.assertEqual(self.window.x() + self.window.width() // 2, 400)
        self.assertEqual(self.window.y() + self.window.height(), 300)


class TestSavedPlaceOffScreen(_WindowCase):
    saved_pos = [-50000, -50000]  # the monitor it was on is gone

    def test_falls_back_to_the_default_place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.window.add_line("фраза")
        self.assertAlmostEqual(self.window.x() + self.window.width() // 2, screen.center().x(), delta=1)


if __name__ == "__main__":
    unittest.main()
