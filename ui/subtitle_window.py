"""
ui/subtitle_window.py — the strip that shows live subtitles over other windows.

    window = SubtitleWindow()
    window.add_line("перевод фразы")
    window.set_status("Слушаю: Динамики", "ok")

Always on top, never takes the focus (a game keeps the keyboard) and kept out of screen
captures like the result popup (OCR and live monitoring must not read the subtitles
back). Like the popup it follows Settings → Popup (ui/overlay_behavior.py): translucent
until the cursor is over it, and with "click-through" on, clicks pass to the window
below unless Alt is held. It shows the last ``MAX_LINES`` translations, the older ones dimmed,
and hides itself when nothing was said for ``LINE_TTL_MS``. Dragging moves it; the
place (bottom-centre point) is saved to ``config.SUBTITLES_POS``.

Reading pace: in lively speech phrases arrive faster than they can be read. A new line
therefore waits until the one on screen has had its reading time (its length at
``READ_CHARS_PER_S``, between ``MIN_HOLD_MS`` and ``MAX_HOLD_MS``); interim text is not
shown during that time either. When more than ``MAX_WAITING`` lines are waiting, the
oldest are shown at once, so the strip never falls far behind the speech.
"""

from __future__ import annotations

import time
from collections import deque

from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

import config
from ui import overlay_behavior, theme

MAX_LINES = 3
LINE_TTL_MS = 8000
#: Reading pace: how long a line stays the newest one before the next may replace it.
READ_CHARS_PER_S = 18
MIN_HOLD_MS = 1500
MAX_HOLD_MS = 5000
#: Lines allowed to wait for their turn; beyond that the oldest are shown without a hold.
MAX_WAITING = 2
STATUS_TTL_MS = 5000
ERROR_TTL_MS = 12000
_MAX_WIDTH = 900
_BOTTOM_MARGIN = 0.12  # of the screen height, for the default place
_CARD_BORDER = 1  # px, the frame drawn by theme.panel_css


def _now() -> float:
    return time.monotonic()


class SubtitleWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # see _exclude_from_capture()
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.SizeAllCursor)

        self._lines: list[str] = []
        self._partial = ""  # interim text of the phrase still being spoken
        self._waiting: deque[str] = deque()  # lines that arrived before the newest one was read
        self._shown_at = 0.0  # when the newest line appeared (_now())
        self._status = ""
        self._drag_offset: QPoint | None = None
        self._drag_from = QPoint()  # the anchor when the drag began
        self._anchor = self._initial_anchor()  # bottom-centre point of the strip
        self._watcher = overlay_behavior.EngageWatcher(self)
        self.setWindowOpacity(overlay_behavior.rest_opacity())

        p = theme.current()
        self.setObjectName("subtitleWindow")
        self.setStyleSheet(f"#subtitleWindow {{ background: {p.bg}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame()
        self._card.setObjectName("subtitleCard")
        self._card.setStyleSheet(theme.panel_css("subtitleCard", background=p.bg, border=p.dim))
        outer.addWidget(self._card)
        box = QVBoxLayout(self._card)
        box.setContentsMargins(18, 10, 18, 12)
        box.setSpacing(4)
        self._box = box

        self._status_label = self._label(theme.text_css(p.muted, 9))
        self._old_label = self._label(theme.text_css(p.muted, 13, display=True))
        self._new_label = self._label(theme.text_css(p.text, 16, display=True))
        for label in (self._status_label, self._old_label, self._new_label):
            box.addWidget(label)

        self._line_timer = QTimer(self)
        self._line_timer.setSingleShot(True)
        self._line_timer.setInterval(LINE_TTL_MS)
        self._line_timer.timeout.connect(self.clear_lines)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._show_waiting)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_TTL_MS)
        self._status_timer.timeout.connect(lambda: self.set_status(""))
        self._refresh()

    @staticmethod
    def _label(css: str) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        label.setTextFormat(Qt.PlainText)  # recognised speech is never markup
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(css)
        return label

    # ── Content ──────────────────────────────────────────

    def add_line(self, text: str) -> None:
        """Show a new subtitle once the one on screen has had its reading time.

        The previous lines move up and are dimmed.
        """
        text = (text or "").strip()
        if not text:
            return
        self._waiting.append(text)
        self._show_waiting()

    def _show_waiting(self) -> None:
        while self._waiting:
            wait = self._hold_left_ms()
            if wait > 0 and len(self._waiting) <= MAX_WAITING:
                self._hold_timer.start(wait)
                return
            self._lines = (self._lines + [self._waiting.popleft()])[-MAX_LINES:]
            self._partial = ""
            self._shown_at = _now()
            self._line_timer.start()
            self._refresh()
        self._hold_timer.stop()

    def _hold_left_ms(self) -> int:
        """Milliseconds the newest line still needs to be read; 0 when it may be replaced."""
        if not self._lines:
            return 0
        hold = min(MAX_HOLD_MS, max(MIN_HOLD_MS, len(self._lines[-1]) * 1000 // READ_CHARS_PER_S))
        return max(0, hold - int((_now() - self._shown_at) * 1000))

    def waiting(self) -> list[str]:
        return list(self._waiting)

    def set_partial(self, text: str) -> None:
        """Show the phrase still being spoken; the next call or ``add_line`` replaces it.

        Skipped while lines are waiting or the newest line is still being read: the next
        interim text arrives in about a second anyway.
        """
        text = (text or "").strip()
        if not text or self._waiting or (not self._partial and self._hold_left_ms() > 0):
            return
        self._partial = text
        self._line_timer.start()
        self._refresh()

    def partial_text(self) -> str:
        return self._partial

    def clear_lines(self) -> None:
        self._lines = []
        self._waiting.clear()
        self._hold_timer.stop()
        self._partial = ""
        self._line_timer.stop()
        self._refresh()

    def set_status(self, message: str, kind: str = "info") -> None:
        """A small line above the subtitles; it goes away after a few seconds."""
        self._status = (message or "").strip()
        p = theme.current()
        color = {"error": p.error, "warn": p.warn, "ok": p.ok}.get(kind, p.muted)
        self._status_label.setStyleSheet(theme.text_css(color, 9))
        if self._status:
            self._status_timer.start(ERROR_TTL_MS if kind == "error" else STATUS_TTL_MS)
        else:
            self._status_timer.stop()
        self._refresh()

    def lines(self) -> list[str]:
        return list(self._lines)

    def status_text(self) -> str:
        return self._status

    def _refresh(self) -> None:
        shown = (self._lines + ([self._partial + " …"] if self._partial else []))[-MAX_LINES:]
        older = shown[:-1]
        self._status_label.setText(self._status)
        self._status_label.setVisible(bool(self._status))
        self._old_label.setText("\n".join(older))
        self._old_label.setVisible(bool(older))
        self._new_label.setText(shown[-1] if shown else "")
        self._new_label.setVisible(bool(shown))
        if not shown and not self._status:
            self.hide()
            return
        self._fit()
        if not self.isVisible():
            self.show()

    # ── Geometry ─────────────────────────────────────────

    def _screen_rect(self):
        screen = QApplication.screenAt(self._anchor - QPoint(0, 20)) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _initial_anchor(self) -> QPoint:
        saved = getattr(config, "SUBTITLES_POS", None)
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                point = QPoint(int(saved[0]), int(saved[1]))
            except (TypeError, ValueError):
                point = None
            if point is not None and QApplication.screenAt(point - QPoint(0, 20)) is not None:
                return point  # else that monitor is gone: the default place
        rect = QApplication.primaryScreen().availableGeometry()
        return QPoint(rect.center().x(), rect.bottom() - int(rect.height() * _BOTTOM_MARGIN))

    def _fit(self) -> None:
        """Size the strip to its text and keep its bottom-centre point where it is."""
        width = min(_MAX_WIDTH, int(self._screen_rect().width() * 0.7))
        height = self._height_for(width)
        before = self.pos()
        self.setFixedSize(width, height)
        self.move(self._anchor.x() - width // 2, self._anchor.y() - height)
        if self._drag_offset is not None:
            # Resized under the cursor: keep the drag from snapping the strip back.
            self._drag_offset -= self.pos() - before

    def _height_for(self, width: int) -> int:
        """Height that holds every visible line wrapped at *width*.

        Counted from the labels themselves: right after a label was shown, hidden or given
        a longer text, the layout still answers with its cached height and the text would
        run past the bottom edge.
        """
        margins = self._box.contentsMargins()
        inner = width - margins.left() - margins.right() - 2 * _CARD_BORDER
        labels = [label for label in (self._status_label, self._old_label, self._new_label) if not label.isHidden()]
        text = sum(max(label.heightForWidth(inner), label.sizeHint().height()) for label in labels)
        spacing = self._box.spacing() * max(0, len(labels) - 1)
        return margins.top() + margins.bottom() + 2 * _CARD_BORDER + text + spacing

    def _bottom_centre(self) -> QPoint:
        return QPoint(self.x() + self.width() // 2, self.y() + self.height())

    def show(self) -> None:
        super().show()
        self._exclude_from_capture()
        self._watcher.start()

    def hideEvent(self, event) -> None:
        self._watcher.stop()
        super().hideEvent(event)

    def _exclude_from_capture(self) -> None:
        overlay_behavior.exclude_from_capture(self)

    # ── Dragging ─────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.pos()
            self._drag_from = QPoint(self._anchor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPos() - self._drag_offset)
            # A line that arrives during the drag is fitted around the place it is at now.
            self._anchor = self._bottom_centre()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is None:
            return
        self._drag_offset = None
        self._anchor = self._bottom_centre()
        if self._anchor != self._drag_from:
            config.SUBTITLES_POS = [self._anchor.x(), self._anchor.y()]
