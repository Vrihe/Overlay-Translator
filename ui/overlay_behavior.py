"""
ui/overlay_behavior.py — what makes the always-on-top overlays (the result popup and the
subtitle strip) unobtrusive: translucent at rest, solid when the user reaches for them,
optionally transparent to clicks, and never part of a screen capture.

    watcher = EngageWatcher(widget, on_change)   # on_change(engaged: bool)
    watcher.start()                              # while the widget is shown
    watcher.stop()

An overlay is **engaged** while the cursor is over it. With "click-through" on it does
not receive the mouse at all, so it is engaged only while Alt is held with the cursor
over it; a pressed mouse button keeps it engaged until released (a drag or a resize may
leave the window for a moment). The watcher polls: a click-through window gets no mouse
events to react to, and Qt's enter / leave events are not reliable for windows shown
under a resting cursor.

Engaged → opacity 1.0 and normal mouse input. At rest → ``config.POPUP_OPACITY`` and,
with click-through, ``WS_EX_TRANSPARENT`` (clicks go to the window below). The settings
are read on every poll, so a change in Settings applies to an open overlay at once.

Neither translucency (``setWindowOpacity``) nor the click-through style breaks
``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)``; ``WA_TranslucentBackground`` would.
"""

from __future__ import annotations

import ctypes
import sys

from PyQt5.QtCore import QObject, Qt, QTimer
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication

import config

MIN_OPACITY = 40  # percent; below it the text is unreadable
MAX_OPACITY = 100
POLL_MS = 100

#: SetWindowDisplayAffinity: shown on screen, left out of every capture.
_WDA_EXCLUDEFROMCAPTURE = 0x11
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x80000
_WS_EX_TRANSPARENT = 0x20
_VK_MENU = 0x12  # Alt


def click_through() -> bool:
    return bool(getattr(config, "POPUP_CLICK_THROUGH", False))


def compact() -> bool:
    return bool(getattr(config, "POPUP_COMPACT", False))


def rest_opacity() -> float:
    """Window opacity of an overlay nobody is reaching for (0.4 – 1.0)."""
    try:
        percent = int(getattr(config, "POPUP_OPACITY", MAX_OPACITY))
    except (TypeError, ValueError):
        percent = MAX_OPACITY  # hand-edited settings.json
    opacity = max(MIN_OPACITY, min(MAX_OPACITY, percent)) / 100
    # Click-through needs a layered window, and Qt drops that style at exactly 1.0.
    return min(opacity, 0.99) if click_through() else opacity


def alt_down() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(_VK_MENU) & 0x8000)
    except Exception:
        return False


def exclude_from_capture(widget) -> None:
    """Keep *widget* out of screen captures (Windows 10 2004+).

    Live monitoring and OCR capture the screen: an overlay lying over the watched region
    would count as a change and be read as text, in a loop.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), _WDA_EXCLUDEFROMCAPTURE)
    except Exception:
        pass  # older Windows: the overlay stays visible to captures


def set_click_through(widget, enabled: bool) -> None:
    """Let mouse input pass through *widget* to whatever is below it (or stop doing so)."""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = int(widget.winId())
        style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        wanted = style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT if enabled else style & ~_WS_EX_TRANSPARENT
        if wanted != style:
            user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, wanted)
    except Exception:
        pass  # the overlay stays clickable


class EngageWatcher(QObject):
    """Tracks whether the user reaches for an overlay and applies opacity / click-through."""

    def __init__(self, widget, on_change=None) -> None:
        super().__init__(widget)
        self._widget = widget
        self._on_change = on_change
        self._applied = None  # (engaged, opacity, click-through, compact) last put on the window
        self.engaged = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self._applied = None  # a re-shown window has lost its click-through style
        self.poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _cursor_inside(self) -> bool:
        return self._widget.frameGeometry().contains(QCursor.pos())

    def _wanted(self) -> bool:
        if self.engaged and QApplication.mouseButtons() != Qt.NoButton:
            return True  # mid-drag / mid-resize
        if not self._cursor_inside():
            return False
        return alt_down() if click_through() else True

    def poll(self) -> None:
        engaged = self._wanted()
        state = (engaged, rest_opacity(), click_through(), compact())
        if state == self._applied:
            return
        self._applied = state
        self._widget.setWindowOpacity(1.0 if engaged else state[1])
        set_click_through(self._widget, state[2] and not engaged)
        self.engaged = engaged
        if self._on_change is not None:
            self._on_change(engaged)  # also after a settings change: the overlay re-syncs
