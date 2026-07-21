"""
ui/result_popup.py — floating popup that shows OCR text + translation.

The popup appears near the selected region, stays on top of all windows,
and auto-closes after a configurable timeout (default 10 s) or when the
user clicks anywhere outside it.  Pressing Escape also dismisses it.
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QApplication, QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, QEvent
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath, QCursor

import config


class ResultPopup(QWidget):
    """Floating popup displaying source text and its translation."""

    _MAX_WIDTH = 480
    _AUTO_CLOSE_MS = 10_000       # auto-close after 10 seconds
    _MARGIN = 12                  # gap between popup and selection edge

    def __init__(
        self,
        source_text: str,
        translated_text: str,
        anchor: QRect | None = None,
        *,
        is_error: bool = False,
        parent=None,
    ):
        """
        Parameters
        ----------
        source_text : str
            Original (OCR) text.
        translated_text : str
            Translated text or error message.
        anchor : QRect, optional
            Selection rectangle in global screen coords — the popup
            will be positioned near this rectangle.
        is_error : bool
            If True, the popup is styled as an error notification.
        """
        super().__init__(parent)

        self._source = source_text
        self._translated = translated_text
        self._anchor = anchor
        self._is_error = is_error

        self._setup_window()
        self._build_ui()
        self._position_near_anchor()
        self._start_auto_close()

    # ── Window setup ─────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                 # hide from taskbar
            | Qt.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMaximumWidth(self._MAX_WIDTH)

        # Install event filter to detect clicks outside the popup.
        QApplication.instance().installEventFilter(self)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Container widget for the rounded card.
        self._card = QWidget(self)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(10)

        if self._is_error:
            # Error mode — single label.
            err_label = self._make_label(
                self._translated,
                size=12,
                color="#ff6b6b",
                bold=True,
            )
            card_layout.addWidget(err_label)
        else:
            # ── Source header + text ──
            src_header = self._make_label("ORIGINAL", size=9, color="#888888", bold=True)
            src_body = self._make_label(self._source, size=12, color="#cccccc")
            card_layout.addWidget(src_header)
            card_layout.addWidget(src_body)

            # ── Separator line ──
            sep = QWidget()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background-color: #3a3a3a;")
            card_layout.addWidget(sep)

            # ── Translation header + text ──
            tl_header = self._make_label("ПЕРЕВОД", size=9, color="#888888", bold=True)
            tl_body = self._make_label(self._translated, size=13, color="#ffffff", bold=True)
            card_layout.addWidget(tl_header)
            card_layout.addWidget(tl_body)

        layout.addWidget(self._card)
        self.setLayout(layout)

        # Drop shadow for depth.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self._card.setGraphicsEffect(shadow)

    @staticmethod
    def _make_label(
        text: str,
        *,
        size: int = 12,
        color: str = "#ffffff",
        bold: bool = False,
    ) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        weight = "bold" if bold else "normal"
        label.setStyleSheet(
            f"color: {color}; font-size: {size}pt; font-weight: {weight}; "
            f"font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ── Rounded card painting ────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        # Slightly inset so the shadow is visible.
        r = self.rect().adjusted(6, 4, -6, -6)
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 14, 14)

        bg = QColor("#1e1e2e") if not self._is_error else QColor("#2a1a1a")
        painter.fillPath(path, bg)
        painter.end()

    # ── Positioning ──────────────────────────────────────

    def _position_near_anchor(self) -> None:
        """Place the popup just below (or above) the selection rectangle."""
        self.adjustSize()
        popup_size = self.size()

        if self._anchor is None:
            # Fallback: centre of the screen with the cursor.
            cursor = QCursor.pos()
            screen = self._screen_at(cursor)
            sg = screen.availableGeometry()
            x = sg.x() + (sg.width() - popup_size.width()) // 2
            y = sg.y() + (sg.height() - popup_size.height()) // 2
            self.move(x, y)
            return

        anchor = self._anchor
        cursor = QCursor.pos()
        screen = self._screen_at(cursor)
        sg = screen.availableGeometry()

        # Prefer placing below the selection.
        x = anchor.left() + (anchor.width() - popup_size.width()) // 2
        y = anchor.bottom() + self._MARGIN

        # If it doesn't fit below, place above.
        if y + popup_size.height() > sg.bottom():
            y = anchor.top() - popup_size.height() - self._MARGIN

        # Clamp horizontally.
        if x < sg.left():
            x = sg.left() + self._MARGIN
        if x + popup_size.width() > sg.right():
            x = sg.right() - popup_size.width() - self._MARGIN

        # Clamp vertically (final safety).
        if y < sg.top():
            y = sg.top() + self._MARGIN

        self.move(x, y)

    @staticmethod
    def _screen_at(pos: QPoint):
        for screen in QApplication.screens():
            if screen.geometry().contains(pos):
                return screen
        return QApplication.primaryScreen()

    # ── Auto-close timer ─────────────────────────────────

    def _start_auto_close(self) -> None:
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_close)
        self._timer.start(self._AUTO_CLOSE_MS)

    def _fade_close(self) -> None:
        self.close()

    # ── Close on outside click / Escape ──────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            # If the click is outside our geometry, close.
            if not self.geometry().contains(event.globalPos()):
                self.close()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
