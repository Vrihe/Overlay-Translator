"""
ui/title_bar.py — HUD title bar for the main window (Windows).

Windows 10 cannot colour a native title bar, so the main window draws its own strip in
the palette colours. The window keeps its native WS_CAPTION / WS_THICKFRAME styles, so
Aero Snap, the minimise / maximise animations, the Alt+Space menu and edge resizing
still come from Windows: WM_NCCALCSIZE hands the whole window to the client area and
WM_NCHITTEST reports the resize edges and, for the strip outside its buttons,
HTCAPTION (``native_event``, called from ``MainWindow.nativeEvent``), so dragging,
double-click maximise and the right-click system menu are native too.
"""

import ctypes
import sys
from ctypes import wintypes

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QPushButton, QWidget

from ui import icons, theme

ENABLED = sys.platform == "win32"

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_HTCAPTION = 2
# (left, right, top, bottom) → hit-test code
_HIT_CODES = {
    (True, False, False, False): 10,   # HTLEFT
    (False, True, False, False): 11,   # HTRIGHT
    (False, False, True, False): 12,   # HTTOP
    (True, False, True, False): 13,    # HTTOPLEFT
    (False, True, True, False): 14,    # HTTOPRIGHT
    (False, False, False, True): 15,   # HTBOTTOM
    (True, False, False, True): 16,    # HTBOTTOMLEFT
    (False, True, False, True): 17,    # HTBOTTOMRIGHT
}
_RESIZE_BORDER = 6  # logical px

_GWL_STYLE = -16
_WS_FRAME_STYLES = (
    0x00C00000    # WS_CAPTION
    | 0x00040000  # WS_THICKFRAME
    | 0x00080000  # WS_SYSMENU
    | 0x00020000  # WS_MINIMIZEBOX
    | 0x00010000  # WS_MAXIMIZEBOX
)
_SWP_FRAMECHANGED = 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010  # + NOSIZE NOMOVE NOZORDER NOACTIVATE

HEIGHT = 32


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


def _user32():
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    return u


def install_native_frame(window: QWidget) -> None:
    """Give a FramelessWindowHint window back the native frame styles (snap, animations)."""
    if not ENABLED:
        return
    try:
        u = _user32()
        hwnd = int(window.winId())
        style = u.GetWindowLongPtrW(hwnd, _GWL_STYLE)
        u.SetWindowLongPtrW(hwnd, _GWL_STYLE, style | _WS_FRAME_STYLES)
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAMECHANGED)
    except Exception:
        pass


def _frame_thickness(hwnd) -> int:
    """Width of the invisible resize frame Windows adds around a maximised window."""
    u = ctypes.windll.user32
    try:
        dpi = u.GetDpiForWindow(hwnd)
        return u.GetSystemMetricsForDpi(32, dpi) + u.GetSystemMetricsForDpi(92, dpi)
    except Exception:  # pre-1607 Windows 10
        return u.GetSystemMetrics(32) + u.GetSystemMetrics(92)


def native_event(window: QWidget, title_bar: "TitleBar", message) -> tuple[bool, int] | None:
    """Handle the frame messages for ``window``; None lets Qt process the message."""
    msg = wintypes.MSG.from_address(int(message))
    if msg.message == _WM_NCCALCSIZE:
        if msg.wParam:
            u = ctypes.windll.user32
            if u.IsZoomed(msg.hWnd):
                # A maximised window overhangs the screen by its frame: pull the client in.
                b = _frame_thickness(msg.hWnd)
                r = _NCCALCSIZE_PARAMS.from_address(msg.lParam).rgrc[0]
                r.left += b
                r.top += b
                r.right -= b
                r.bottom -= b
        return True, 0
    if msg.message == _WM_NCHITTEST:
        if not window.isMaximized():
            u = ctypes.windll.user32
            pt = wintypes.POINT()
            rc = wintypes.RECT()
            u.GetCursorPos(ctypes.byref(pt))
            u.GetWindowRect(msg.hWnd, ctypes.byref(rc))
            b = max(1, int(_RESIZE_BORDER * window.devicePixelRatioF()))
            key = (pt.x < rc.left + b, pt.x >= rc.right - b,
                   pt.y < rc.top + b, pt.y >= rc.bottom - b)
            code = _HIT_CODES.get(key)
            if code is not None:
                return True, code
        if title_bar is not None and title_bar.isVisible():
            local = title_bar.mapFromGlobal(QCursor.pos())
            if title_bar.rect().contains(local) and not isinstance(
                    title_bar.childAt(local), QAbstractButton):
                return True, _HTCAPTION
    return None


class TitleBar(QWidget):
    """32 px strip: ``// TITLE`` on the left, minimise / maximise / close on the right."""

    def __init__(self, window: QWidget, title: str):
        super().__init__(window)
        self._window = window
        p = theme.current()
        self.setObjectName("hudTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(HEIGHT)
        self.setStyleSheet(
            f"#hudTitleBar {{ background: {p.rail}; border: none; border-bottom: 1px solid {p.line}; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 0, 1)
        row.setSpacing(0)

        caption = QLabel(f"<span style='color:{p.accent};'>//</span> {title.upper()}")
        caption.setTextFormat(Qt.RichText)
        caption.setFont(theme.display_font(9, spacing=118))
        caption.setStyleSheet(f"color: {p.text_soft}; background: transparent;")
        row.addWidget(caption)
        row.addStretch()

        self._btn_min = self._button("minimize", window.showMinimized)
        self._btn_max = self._button("maximize", self._toggle_maximized)
        self._btn_close = self._button("close", window.close, danger=True)
        for btn in (self._btn_min, self._btn_max, self._btn_close):
            row.addWidget(btn)

    def _button(self, icon_name: str, slot, *, danger: bool = False) -> QPushButton:
        p = theme.current()
        btn = QPushButton()
        btn.setFixedSize(46, HEIGHT - 1)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setIconSize(QSize(12, 12))
        btn.setIcon(icons.icon(icon_name, p.text_soft, 12))
        hover = p.error if danger else p.active
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 0; }"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {theme.rgba(hover, 200)}; }}"
        )
        btn.clicked.connect(slot)
        return btn

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def sync_state(self) -> None:
        """Swap the maximise / restore icon after a window state change."""
        name = "restore" if self._window.isMaximized() else "maximize"
        self._btn_max.setIcon(icons.icon(name, theme.current().text_soft, 12))
