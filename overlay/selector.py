"""
overlay/selector.py — fullscreen transparent overlay for rectangular region selection.

Shows a semi-transparent dark background over all monitors.  The user drags
a rectangle with the mouse; on release the widget emits ``region_selected``
with (x1, y1, x2, y2) in global screen coordinates and closes itself.
Pressing Escape cancels the selection.
"""

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont


class RegionSelector(QWidget):
    """Full-screen transparent overlay for selecting a screen region."""

    # Emitted with (x1, y1, x2, y2) in global screen coords.
    region_selected = pyqtSignal(int, int, int, int)
    # Emitted when the user presses Escape.
    selection_cancelled = pyqtSignal()

    # ── Visual tunables ──────────────────────────────────
    _OVERLAY_COLOR = QColor(0, 0, 0, 120)        # dark semi-transparent bg
    _SELECTION_FILL = QColor(0, 174, 255, 30)     # light blue fill inside rect
    _BORDER_COLOR = QColor(0, 174, 255, 220)      # bright blue border
    _BORDER_WIDTH = 2
    _HINT_COLOR = QColor(255, 255, 255, 180)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._origin = QPoint()       # mouse-down point (widget coords)
        self._current = QPoint()      # current mouse position
        self._selecting = False

        # ── Window flags ─────────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                 # hide from taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

    # ── Public API ───────────────────────────────────────

    def activate(self) -> None:
        """Cover the entire virtual desktop and show the overlay."""
        virtual_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(virtual_geo)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    # ── Mouse events ─────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._origin = event.pos()
            self._current = event.pos()
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            rect = QRect(self._origin, event.pos()).normalized()

            # Ignore tiny accidental clicks (< 4 px either side).
            if rect.width() < 4 or rect.height() < 4:
                self.update()
                return

            # Convert widget-local coords → global screen coords.
            top_left = self.mapToGlobal(rect.topLeft())
            bottom_right = self.mapToGlobal(rect.bottomRight())

            self.close()
            self.region_selected.emit(
                top_left.x(), top_left.y(),
                bottom_right.x(), bottom_right.y(),
            )

    # ── Keyboard events ──────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._selecting = False
            self.close()
            self.selection_cancelled.emit()
        else:
            super().keyPressEvent(event)

    # ── Painting ─────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        full = self.rect()

        if self._selecting and self._origin != self._current:
            sel = QRect(self._origin, self._current).normalized()

            # Dark overlay around the selection (four rectangles).
            oc = self._OVERLAY_COLOR
            # top strip
            painter.fillRect(
                QRect(full.left(), full.top(), full.width(),
                      sel.top() - full.top()),
                oc,
            )
            # bottom strip
            painter.fillRect(
                QRect(full.left(), sel.bottom() + 1, full.width(),
                      full.bottom() - sel.bottom()),
                oc,
            )
            # left strip (between top and bottom strips)
            painter.fillRect(
                QRect(full.left(), sel.top(),
                      sel.left() - full.left(), sel.height() + 1),
                oc,
            )
            # right strip
            painter.fillRect(
                QRect(sel.right() + 1, sel.top(),
                      full.right() - sel.right(), sel.height() + 1),
                oc,
            )

            # Light fill inside the selected rectangle.
            painter.fillRect(sel, self._SELECTION_FILL)

            # Border around the selection.
            pen = QPen(self._BORDER_COLOR, self._BORDER_WIDTH)
            painter.setPen(pen)
            painter.drawRect(sel)

            # Size label near the bottom-right corner of the selection.
            global_tl = self.mapToGlobal(sel.topLeft())
            global_br = self.mapToGlobal(sel.bottomRight())
            w = global_br.x() - global_tl.x()
            h = global_br.y() - global_tl.y()
            label = f"{w} × {h}"
            painter.setFont(QFont("Segoe UI", 10))
            painter.setPen(QColor(255, 255, 255, 210))
            label_rect = painter.fontMetrics().boundingRect(label)
            lx = sel.right() - label_rect.width() - 6
            ly = sel.bottom() - 6
            # background for readability
            bg = QRect(lx - 4, ly - label_rect.height() - 2,
                       label_rect.width() + 8, label_rect.height() + 6)
            painter.fillRect(bg, QColor(0, 0, 0, 160))
            painter.drawText(lx, ly, label)
        else:
            # No active selection — draw full dark overlay + hint text.
            painter.fillRect(full, self._OVERLAY_COLOR)
            painter.setFont(QFont("Segoe UI", 14))
            painter.setPen(self._HINT_COLOR)
            painter.drawText(full, Qt.AlignCenter,
                             "Выделите область для перевода\nEsc — отмена")

        painter.end()
