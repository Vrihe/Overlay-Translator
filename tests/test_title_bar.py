"""
tests/test_title_bar.py — a click on the drawn caption activates the main window first,
so the native caption drag starts even while the result popup is the active window.

No window is created: native_event runs on a hand-built MSG with user32 mocked.
"""

import ctypes
import unittest
from ctypes import wintypes
from unittest import mock

from PyQt5.QtCore import QPoint

from ui import title_bar


def _native_event(message: int, l_param: int):
    msg = wintypes.MSG()
    msg.hWnd = 0x1234
    msg.message = message
    msg.lParam = l_param
    with mock.patch.object(title_bar.ctypes, "windll") as windll:
        result = title_bar.native_event(mock.Mock(), None, ctypes.addressof(msg))
    return result, windll.user32


class TestCaptionActivation(unittest.TestCase):
    def test_caption_click_activates_the_window(self):
        result, user32 = _native_event(title_bar._WM_MOUSEACTIVATE, (0x0201 << 16) | title_bar._HTCAPTION)
        self.assertEqual(result, (True, title_bar._MA_ACTIVATE))
        user32.SetForegroundWindow.assert_called_once_with(0x1234)

    def test_client_click_is_left_to_qt(self):
        result, user32 = _native_event(title_bar._WM_MOUSEACTIVATE, (0x0201 << 16) | 1)  # HTCLIENT
        self.assertIsNone(result)
        user32.SetForegroundWindow.assert_not_called()


class TestTitleBarPoint(unittest.TestCase):
    """The hit-test point comes from the message and the native client origin only."""

    def _point(self, screen_x, screen_y, origin=(100, 200), dpr=1.0, bar_offset=(1, 1)):
        msg = wintypes.MSG()
        msg.hWnd = 0x1234
        msg.lParam = ((screen_y & 0xFFFF) << 16) | (screen_x & 0xFFFF)
        window = mock.Mock()
        window.devicePixelRatioF.return_value = dpr
        bar = mock.Mock()
        bar.mapTo.return_value = QPoint(*bar_offset)

        def client_to_screen(_hwnd, pt_ref):
            pt = ctypes.cast(pt_ref, ctypes.POINTER(wintypes.POINT)).contents
            pt.x, pt.y = origin

        with mock.patch.object(title_bar.ctypes, "windll") as windll:
            windll.user32.ClientToScreen.side_effect = client_to_screen
            with mock.patch.object(title_bar.ctypes, "byref", side_effect=ctypes.pointer):
                return title_bar._title_bar_point(window, bar, msg)

    def test_point_relative_to_native_client_origin(self):
        self.assertEqual(self._point(150, 216), QPoint(49, 15))

    def test_high_dpi_scales_to_logical_pixels(self):
        self.assertEqual(self._point(300, 260, origin=(100, 200), dpr=2.0), QPoint(99, 29))

    def test_negative_coordinates_on_a_left_monitor(self):
        self.assertEqual(self._point(-1800, 210, origin=(-1900, 200)), QPoint(99, 9))


if __name__ == "__main__":
    unittest.main()
