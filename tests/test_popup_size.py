"""
tests/test_popup_size.py — result popup size saved across launches (config.POPUP_SIZE).

No popup is shown: only the parsing / clamping of the saved value and the write once a
resize drag ends.
"""

import unittest
from unittest import mock

from PyQt5.QtCore import QSize

import config
from ui.result_popup import ResultPopup

_MIN = QSize(ResultPopup._MIN_WIDTH, ResultPopup._MIN_HEIGHT)
_MAX = QSize(ResultPopup._MAX_WIDTH, ResultPopup._MAX_HEIGHT)


class TestParseSize(unittest.TestCase):
    def test_no_saved_size_fits_text(self):
        for value in (None, [], "", "abc", [1], [1, 2, 3], ["x", 2], {"w": 1}):
            self.assertIsNone(ResultPopup._parse_size(value), value)

    def test_valid_size(self):
        self.assertEqual(ResultPopup._parse_size([420, 200]), QSize(420, 200))
        self.assertEqual(ResultPopup._parse_size(("420", "200")), QSize(420, 200))

    def test_clamped_to_limits(self):
        self.assertEqual(ResultPopup._parse_size([1, 1]), _MIN)
        self.assertEqual(ResultPopup._parse_size([99999, 99999]), _MAX)

    def test_saved_size_reads_config(self):
        with mock.patch.object(type(config), "POPUP_SIZE", new_callable=mock.PropertyMock, return_value=[500, 300]):
            self.assertEqual(ResultPopup.saved_size(), QSize(500, 300))


class TestFinishResize(unittest.TestCase):
    def _fake_popup(self, resized: bool):
        popup = mock.Mock(spec=ResultPopup)
        popup._resized = resized
        popup.width.return_value = 450
        popup.height.return_value = 220
        return popup

    def test_saves_once_after_a_resize(self):
        popup = self._fake_popup(resized=True)
        with mock.patch.object(type(config), "POPUP_SIZE", new_callable=mock.PropertyMock) as prop:
            ResultPopup._finish_resize(popup)
        prop.assert_called_once_with([450, 220])
        self.assertFalse(popup._resized)

    def test_plain_click_or_drag_saves_nothing(self):
        popup = self._fake_popup(resized=False)
        with mock.patch.object(type(config), "POPUP_SIZE", new_callable=mock.PropertyMock) as prop:
            ResultPopup._finish_resize(popup)
        prop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
