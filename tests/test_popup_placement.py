"""
tests/test_popup_placement.py — the result popup stays under the selection but steps
aside from the app's own windows (the main window) when the screen allows it.

Pure geometry: ResultPopup._place runs without any window.
"""

import unittest

from PyQt5.QtCore import QPoint, QRect, QSize

from ui.result_popup import ResultPopup

SCREEN = QRect(0, 0, 1920, 1040)
SIZE = QSize(400, 200)
M = 10


def _place(anchor, avoid=()):
    return ResultPopup._place(SIZE, anchor, SCREEN, list(avoid), M)


class TestPlacement(unittest.TestCase):

    def test_under_the_anchor_by_default(self):
        anchor = QRect(700, 100, 600, 100)
        self.assertEqual(_place(anchor), QPoint(800, 100 + 100 - 1 + M))

    def test_above_when_no_room_below(self):
        anchor = QRect(700, 900, 600, 100)
        self.assertEqual(_place(anchor), QPoint(800, 900 - 200 - M))

    def test_free_spot_is_kept_even_with_windows_around(self):
        anchor = QRect(700, 100, 600, 100)
        main = QRect(0, 600, 600, 400)
        self.assertEqual(_place(anchor, [main]), _place(anchor))

    def test_steps_off_the_main_window(self):
        anchor = QRect(700, 100, 600, 100)
        main = QRect(400, 250, 900, 650)  # its title bar sits right under the selection
        p = _place(anchor, [main])
        popup = QRect(p, SIZE)
        self.assertFalse(popup.intersects(main))
        self.assertFalse(popup.intersects(anchor))
        self.assertTrue(SCREEN.contains(popup))

    def test_picks_the_nearest_free_spot(self):
        # Under the selection is the main window, above it there is no room:
        # the popup stays at the same height, just left of the window (610 px away;
        # right of it is as far, below it is 617 px away).
        anchor = QRect(700, 100, 600, 100)
        main = QRect(600, 215, 800, 600)
        self.assertEqual(_place(anchor, [main]), QPoint(600 - 400 - M, 199 + M))

    def test_no_free_spot_keeps_the_usual_place(self):
        anchor = QRect(700, 100, 600, 100)
        maximized = QRect(SCREEN)
        self.assertEqual(_place(anchor, [maximized]), _place(anchor))

    def test_without_anchor_centres_on_screen(self):
        self.assertEqual(_place(None), QPoint((1920 - 400) // 2, (1040 - 200) // 2))


if __name__ == "__main__":
    unittest.main()
