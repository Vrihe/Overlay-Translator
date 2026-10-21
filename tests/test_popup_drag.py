"""
tests/test_popup_drag.py — result popup drag: the top edge moves the window, the OS
runs the move loop when it can.

No popup is shown: the methods run on a mock with the popup's spec.
"""

import unittest
from unittest import mock

from PyQt5.QtCore import QPoint, QRect

from ui.result_popup import ResultPopup


def _fake_popup(*, system_move=True):
    popup = mock.Mock(spec=ResultPopup)
    popup._RESIZE_MARGIN = ResultPopup._RESIZE_MARGIN
    popup.rect.return_value = QRect(0, 0, 400, 200)
    popup._press_pos = QPoint(100, 100)
    popup._drag_offset = QPoint(10, 10)
    popup._is_dragging = False
    popup.windowHandle.return_value.startSystemMove.return_value = system_move
    return popup


class TestResizeEdges(unittest.TestCase):

    def test_top_edge_is_a_drag_handle(self):
        popup = _fake_popup()
        for pos in (QPoint(200, 2), QPoint(2, 2), QPoint(398, 2)):
            edge = ResultPopup._detect_resize_edge(popup, pos)
            self.assertNotIn("t", edge or "", pos)

    def test_other_edges_still_resize(self):
        popup = _fake_popup()
        cases = [((398, 100), "r"), ((2, 100), "l"), ((200, 198), "b"),
                 ((398, 198), "br"), ((2, 198), "bl"), ((200, 100), None)]
        for (x, y), expected in cases:
            self.assertEqual(ResultPopup._detect_resize_edge(popup, QPoint(x, y)), expected, (x, y))


class TestDragMove(unittest.TestCase):

    def test_small_jitter_does_not_start_a_drag(self):
        popup = _fake_popup()
        self.assertFalse(ResultPopup._drag_move(popup, QPoint(102, 102)))
        popup.windowHandle.assert_not_called()
        popup.move.assert_not_called()

    def test_hands_the_drag_to_the_os(self):
        popup = _fake_popup(system_move=True)
        self.assertTrue(ResultPopup._drag_move(popup, QPoint(120, 100)))
        popup.windowHandle.return_value.startSystemMove.assert_called_once_with()
        popup.move.assert_not_called()
        self.assertIsNone(popup._press_pos)  # the OS eats the release

    def test_falls_back_to_manual_move(self):
        popup = _fake_popup(system_move=False)
        self.assertTrue(ResultPopup._drag_move(popup, QPoint(120, 100)))
        popup.move.assert_called_once_with(QPoint(110, 90))
        self.assertTrue(popup._is_dragging)

        popup.windowHandle.reset_mock()
        ResultPopup._drag_move(popup, QPoint(121, 100))
        popup.windowHandle.assert_not_called()  # one attempt per drag
        popup.move.assert_called_with(QPoint(111, 90))


if __name__ == "__main__":
    unittest.main()
