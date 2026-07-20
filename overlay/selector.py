"""
overlay/selector.py — fullscreen transparent overlay for rectangular region selection.

Multi-monitor aware: computes the bounding rectangle of *all* connected
screens (including those with negative coordinates) and stretches the
overlay across the entire virtual desktop.  The returned coordinates
are always in the global screen coordinate system.
"""

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QCursor


def _virtual_desktop_geometry() -> QRect:
    """Return the bounding QRect that covers every connected screen.

    Works correctly when monitors have negative origins (e.g. a screen
    placed to the left or above the primary monitor).
    """
    screens = QApplication.screens()
    if not screens:
        # Fallback — should never happen with a running QApplication.
        return QRect(0, 0, 1920, 1080)

    united = screens[0].geometry()
    for screen in screens[1:]:
        united = united.united(screen.geometry())
    return united


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

        # Origin of the virtual desktop in global coords.
        # Needed to convert widget-local coords → global coords manually
        # when the virtual desktop starts at a negative origin.
        self._vd_origin = QPoint(0, 0)

        # Rect (in widget-local coords) of the monitor where the hint
        # text should be drawn — determined in activate().
        self._hint_rect = QRect()

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
        """Cover the entire virtual desktop (all monitors) and show."""
        vd = _virtual_desktop_geometry()
        self._vd_origin = vd.topLeft()

        # Determine which monitor currently holds the cursor so we can
        # draw the hint text centered on that specific screen.
        cursor_pos = QCursor.pos()  # global coords
        target_screen = QApplication.primaryScreen()  # fallback
        for screen in QApplication.screens():
            if screen.geometry().contains(cursor_pos):
                target_screen = screen
                break

        # Convert the target screen's global geometry to widget-local
        # coordinates (widget origin == virtual desktop origin).
        sg = target_screen.geometry()
        self._hint_rect = QRect(
            sg.x() - vd.x(),
            sg.y() - vd.y(),
            sg.width(),
            sg.height(),
        )

        # Position the window at the virtual desktop origin and stretch
        # it to cover every pixel across all monitors.
        self.setGeometry(vd)
        self.show()           # show() instead of showFullScreen() so WM
        self.activateWindow() # doesn't clamp us to one monitor.
        self.raise_()

    # ── Coordinate helpers ───────────────────────────────

    def _to_global(self, widget_pt: QPoint) -> QPoint:
        """Convert a widget-local point to global screen coordinates.

        Because the widget's geometry matches the virtual desktop, the
        widget-local origin (0, 0) corresponds to ``self._vd_origin``
        in global coords.
        """
        return widget_pt + self._vd_origin

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
            global_tl = self._to_global(rect.topLeft())
            global_br = self._to_global(rect.bottomRight())

            self.close()
            self.region_selected.emit(
                global_tl.x(), global_tl.y(),
                global_br.x(), global_br.y(),
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
            g_tl = self._to_global(sel.topLeft())
            g_br = self._to_global(sel.bottomRight())
            w = g_br.x() - g_tl.x()
            h = g_br.y() - g_tl.y()
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
            # No active selection — draw full dark overlay + hint text
            # centered on the monitor where the cursor was at activation.
            painter.fillRect(full, self._OVERLAY_COLOR)

            hint_text = "Выделите область для перевода\nEsc — отмена"
            hint_font = QFont("Segoe UI", 14)
            painter.setFont(hint_font)
            fm = painter.fontMetrics()

            # Measure each line independently — boundingRect with a zero-
            # sized rect and TextWordWrap is unreliable for multi-line text.
            lines = hint_text.split("\n")
            line_h = fm.ascent() + fm.descent()
            line_spacing = fm.leading()
            text_w = max(fm.horizontalAdvance(ln) for ln in lines)
            text_h = len(lines) * line_h + max(0, len(lines) - 1) * line_spacing

            pad_x, pad_y = 36, 22
            tw = text_w + pad_x * 2
            th = text_h + pad_y * 2

            # Center the backdrop on the target monitor (widget-local).
            hr = self._hint_rect
            bx = hr.x() + (hr.width() - tw) // 2
            by = hr.y() + (hr.height() - th) // 2
            backdrop = QRect(bx, by, tw, th)

            # Semi-transparent dark pill behind the text.
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(backdrop, 12, 12)

            # Draw the hint text.
            painter.setPen(self._HINT_COLOR)
            painter.drawText(backdrop, Qt.AlignCenter, hint_text)

        painter.end()
