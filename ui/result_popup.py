"""
ui/result_popup.py — lightweight floating popup for translation results.

Design goals:
  • Non-intrusive — compact, semi-transparent, doesn't steal focus
  • Floating — user can drag it anywhere
  • Dismissable — click on it, press Escape, click outside, or wait for timeout
  • Smooth — fade-in on appear, fade-out on dismiss
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout,
    QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QEvent,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath, QCursor

import config


class ResultPopup(QWidget):
    """Compact floating popup showing source text and its translation."""

    _MAX_WIDTH = 420
    _AUTO_CLOSE_MS = config.POPUP_TIMEOUT_SEC * 1000
    _FADE_DURATION = 200          # ms for fade-in / fade-out
    _MARGIN = 10                  # gap between popup and selection edge
    _BG_OPACITY = 0.92            # card background opacity

    def __init__(
        self,
        source_text: str,
        translated_text: str,
        anchor: QRect | None = None,
        *,
        is_error: bool = False,
        parent=None,
    ):
        super().__init__(parent)

        self._source = source_text
        self._translated = translated_text
        self._anchor = anchor
        self._is_error = is_error
        self._drag_pos: QPoint | None = None
        self._closing = False

        self._setup_window()
        self._build_ui()
        self._position_near_anchor()

    # ── Window setup ─────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMaximumWidth(self._MAX_WIDTH)
        self.setCursor(Qt.OpenHandCursor)
        self.setWindowOpacity(0.0)  # start invisible — fade in on show

    # ── Show with fade-in ────────────────────────────────

    def show(self) -> None:
        super().show()
        self.activateWindow()

        # Fade in.
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

        # Start auto-close timer after fade-in.
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._fade_out_and_close)
        self._auto_timer.start(self._AUTO_CLOSE_MS)

    # ── Close with fade-out ──────────────────────────────

    def _fade_out_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InCubic)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)

        self._card = QWidget(self)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(6)

        if self._is_error:
            err = self._make_label(self._translated, size=11, color="#ff6b6b")
            card_layout.addWidget(err)
        else:
            # Source text (compact, dimmed).
            if self._source:
                src = self._make_label(self._source, size=10, color="#999999")
                card_layout.addWidget(src)

                sep = QWidget()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background: rgba(255,255,255,0.08);")
                card_layout.addWidget(sep)

            # Translation (primary content).
            tl = self._make_label(self._translated, size=12, color="#e8e8e8", bold=True)
            card_layout.addWidget(tl)

        layout.addWidget(self._card)

        # Subtle shadow.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 80))
        self._card.setGraphicsEffect(shadow)

    @staticmethod
    def _make_label(text: str, *, size: int = 12, color: str = "#fff", bold: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        weight = "600" if bold else "normal"
        label.setStyleSheet(
            f"color: {color}; font-size: {size}pt; font-weight: {weight}; "
            f"font-family: 'Segoe UI', sans-serif; background: transparent; "
            f"padding: 2px 0;"
        )
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ── Rounded card background ──────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        r = self.rect().adjusted(4, 3, -4, -4)
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 10, 10)

        if self._is_error:
            bg = QColor(40, 20, 20, int(255 * self._BG_OPACITY))
        else:
            bg = QColor(28, 28, 36, int(255 * self._BG_OPACITY))

        painter.fillPath(path, bg)

        # Thin subtle border.
        painter.setPen(QColor(255, 255, 255, 15))
        painter.drawPath(path)
        painter.end()

    # ── Positioning ──────────────────────────────────────

    def _position_near_anchor(self) -> None:
        self.adjustSize()
        ps = self.size()

        if self._anchor is None:
            cursor = QCursor.pos()
            screen = self._screen_at(cursor)
            sg = screen.availableGeometry()
            self.move(
                sg.x() + (sg.width() - ps.width()) // 2,
                sg.y() + (sg.height() - ps.height()) // 2,
            )
            return

        a = self._anchor
        screen = self._screen_at(QPoint(a.center().x(), a.center().y()))
        sg = screen.availableGeometry()

        # Try below selection.
        x = a.left() + (a.width() - ps.width()) // 2
        y = a.bottom() + self._MARGIN

        # If it overflows bottom, try above.
        if y + ps.height() > sg.bottom():
            y = a.top() - ps.height() - self._MARGIN

        # Clamp.
        x = max(sg.left() + self._MARGIN, min(x, sg.right() - ps.width() - self._MARGIN))
        y = max(sg.top() + self._MARGIN, y)

        self.move(x, y)

    @staticmethod
    def _screen_at(pos: QPoint):
        for s in QApplication.screens():
            if s.geometry().contains(pos):
                return s
        return QApplication.primaryScreen()

    # ── Dragging ─────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()

    # ── Close on outside click (deactivation) / Escape ───

    def changeEvent(self, event):
        """Close when the window loses focus (user clicked elsewhere)."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowDeactivate:
            self._fade_out_and_close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._fade_out_and_close()
        else:
            super().keyPressEvent(event)
