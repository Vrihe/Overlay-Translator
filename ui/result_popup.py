"""
ui/result_popup.py — lightweight floating popup and notification helper.

Design goals:
  • Non-intrusive — compact, semi-transparent, instant appearance
  • Resizable & Draggable — stretchable from all 4 edges & 4 corners (max 850x550, min 300x80)
  • Clean header with close button ("✕") — window remains open on focus loss or window body clicks
  • Strict screen bounds — wrapped in QScrollArea, never exceeds monitor bounds
  • Dismissable — close button ("✕"), Escape key, or 10s fallback timeout
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QScrollBar, QFrame, QApplication, QGraphicsDropShadowEffect, QSystemTrayIcon,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QEvent,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QCursor

import config


class ResultPopup(QWidget):
    """Compact floating popup showing source text and its translation, or loading status."""

    _MIN_WIDTH = 300
    _MAX_WIDTH = 850
    _MIN_HEIGHT = 80
    _MAX_HEIGHT = 550
    _RESIZE_MARGIN = 8
    _AUTO_CLOSE_MS = config.POPUP_TIMEOUT_SEC * 1000
    _FADE_DURATION = 150          # ms for smooth fade-out on close
    _MARGIN = 10                  # gap between popup and selection edge
    _BG_OPACITY = 0.92            # card background opacity

    def __init__(
        self,
        source_text: str = "",
        translated_text: str = "",
        anchor: QRect | None = None,
        *,
        is_error: bool = False,
        is_loading: bool = False,
        parent=None,
    ):
        super().__init__(parent)

        self._source = source_text
        self._translated = translated_text
        self._anchor = anchor
        self._is_error = is_error
        self._is_loading = is_loading
        self._closing = False
        self._scroll_area: QScrollArea | None = None
        self._btn_close: QPushButton | None = None

        self._dots_count = 3
        self._dots_timer: QTimer | None = None

        self._press_pos: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._start_geom: QRect | None = None
        self._is_dragging = False
        self._resize_edge: str | None = None

        self._setup_window()
        self._build_ui()
        self._position_near_anchor()
        self._install_click_filter(self)

    # ── Window setup ─────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setWindowOpacity(1.0)  # Instant show — no delay

    # ── Show ─────────────────────────────────────────────

    def show(self) -> None:
        super().show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

        if not self._is_loading:
            self._start_auto_timer()

    def _start_auto_timer(self) -> None:
        if hasattr(self, "_auto_timer") and self._auto_timer.isActive():
            self._auto_timer.stop()
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._fade_out_and_close)
        self._auto_timer.start(self._AUTO_CLOSE_MS)

    # ── Close with fast fade-out ─────────────────────────

    def _fade_out_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True

        if self._dots_timer is not None and self._dots_timer.isActive():
            self._dots_timer.stop()

        if hasattr(self, "_auto_timer") and self._auto_timer.isActive():
            self._auto_timer.stop()

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InCubic)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        if hasattr(self, "_card") and self._card is not None:
            self._card.setParent(None)
            self._card.deleteLater()
            self._card = None

        if self.layout() is not None:
            old_layout = self.layout()
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

        layout = self.layout()
        if layout is None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(0)

        self._card = QWidget(self)
        self._card.setMinimumSize(self._MIN_WIDTH, self._MIN_HEIGHT)
        self._card.setMaximumSize(self._MAX_WIDTH, self._MAX_HEIGHT)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(12, 8, 12, 10)
        card_layout.setSpacing(6)

        # Header bar: Title/loading status on left + Close button ("✕") on right
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 2)
        header_row.setSpacing(6)

        if self._is_loading:
            self._loading_label = self._make_label("Переводим...", size=10, color="#a0a0c0", bold=True)
            header_row.addWidget(self._loading_label)
            self._start_dots_animation()
        else:
            title_text = "Ошибка" if self._is_error else "Перевод"
            title_color = "#ff6b6b" if self._is_error else "#8888aa"
            header_lbl = QLabel(title_text)
            header_lbl.setStyleSheet(f"color: {title_color}; font-size: 9.5pt; font-weight: 600; background: transparent;")
            header_row.addWidget(header_lbl)

        header_row.addStretch()

        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(20, 20)
        self._btn_close.setCursor(Qt.PointingHandCursor)
        self._btn_close.setToolTip("Закрыть окно")
        self._btn_close.setStyleSheet(
            "QPushButton {"
            "  color: #777799; background: transparent; border: none;"
            "  font-family: 'Segoe UI', sans-serif; font-size: 10pt; font-weight: bold;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            "  color: #ff6b6b; background: rgba(255, 255, 255, 0.12);"
            "}"
        )
        self._btn_close.clicked.connect(self._fade_out_and_close)
        header_row.addWidget(self._btn_close)

        card_layout.addLayout(header_row)

        # Scrollable container for text
        self._scroll_area = QScrollArea(self._card)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical {"
            "  background: transparent; width: 6px; margin: 0px; border-radius: 3px;"
            "}"
            "QScrollBar::handle:vertical {"
            "  background: rgba(255, 255, 255, 0.25); min-height: 20px; border-radius: 3px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            "  background: rgba(255, 255, 255, 0.4);"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            "  background: none; height: 0px;"
            "}"
        )

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        if not self._is_loading:
            if self._is_error:
                err = self._make_label(self._translated, size=11, color="#ff6b6b")
                content_layout.addWidget(err)
            else:
                if self._source:
                    src = self._make_label(self._source, size=10, color="#999999")
                    content_layout.addWidget(src)

                    sep = QWidget()
                    sep.setFixedHeight(1)
                    sep.setStyleSheet("background: rgba(255,255,255,0.08);")
                    content_layout.addWidget(sep)

                tl = self._make_label(self._translated, size=12, color="#e8e8e8", bold=True)
                content_layout.addWidget(tl)

        self._scroll_area.setWidget(scroll_content)
        card_layout.addWidget(self._scroll_area)
        layout.addWidget(self._card)

        # Subtle shadow
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

    # ── Animated Dots ("Переводим..." -> "Переводим." -> ...) ──

    def _start_dots_animation(self) -> None:
        if self._dots_timer is not None:
            self._dots_timer.stop()
        self._dots_timer = QTimer(self)
        self._dots_timer.timeout.connect(self._update_dots)
        self._dots_timer.start(350)

    def _update_dots(self) -> None:
        if not self._is_loading or not hasattr(self, "_loading_label"):
            if self._dots_timer is not None:
                self._dots_timer.stop()
            return
        self._dots_count = (self._dots_count % 3) + 1
        dots = "." * self._dots_count
        self._loading_label.setText(f"Переводим{dots}")

    # ── In-place content update ──────────────────────────

    def update_content(self, source_text: str, translated_text: str, *, is_error: bool = False) -> None:
        """Update popup content from loading state to final result in-place,
        fitting the window snugly to the translated content size."""
        if self._closing:
            return

        if self._dots_timer is not None:
            self._dots_timer.stop()

        self._is_loading = False
        self._is_error = is_error
        self._source = source_text
        self._translated = translated_text

        saved_pos = self.pos()

        self._build_ui()
        self._install_click_filter(self._card)
        self._fit_and_adjust_size()
        self.move(saved_pos)

        self._start_auto_timer()

        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()

    def _fit_and_adjust_size(self) -> None:
        """Calculate and set exact window size fitting the content perfectly."""
        self.setMinimumSize(self._MIN_WIDTH + 8, self._MIN_HEIGHT + 8)
        self.setMaximumSize(self._MAX_WIDTH + 8, self._MAX_HEIGHT + 8)
        if self._scroll_area is not None:
            self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.layout().activate()
        self._card.layout().activate()
        if self._scroll_area is not None and self._scroll_area.widget() is not None:
            self._scroll_area.widget().layout().activate()

        hint = self.sizeHint()
        w = max(self._MIN_WIDTH + 8, min(self._MAX_WIDTH + 8, hint.width()))
        h = max(self._MIN_HEIGHT + 8, min(self._MAX_HEIGHT + 8, hint.height()))
        self.resize(w, h)

    # ── Edge detection & Mouse Resizing / Dragging ────────

    def _detect_resize_edge(self, pos: QPoint) -> str | None:
        r = self.rect()
        m = self._RESIZE_MARGIN
        x, y, w, h = pos.x(), pos.y(), r.width(), r.height()

        on_right = (x >= w - m)
        on_bottom = (y >= h - m)
        on_left = (x <= m)
        on_top = (y <= m)

        if on_right and on_bottom:
            return "br"
        elif on_left and on_bottom:
            return "bl"
        elif on_right and on_top:
            return "tr"
        elif on_left and on_top:
            return "tl"
        elif on_right:
            return "r"
        elif on_bottom:
            return "b"
        elif on_left:
            return "l"
        elif on_top:
            return "t"
        return None

    def _update_cursor_for_edge(self, edge: str | None) -> None:
        if edge in ("br", "tl"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge in ("bl", "tr"):
            self.setCursor(Qt.SizeBDiagCursor)
        elif edge in ("r", "l"):
            self.setCursor(Qt.SizeHorCursor)
        elif edge in ("b", "t"):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)

    def _perform_resize(self, global_pos: QPoint) -> None:
        if not self._resize_edge or self._press_pos is None or self._start_geom is None:
            return

        dx = global_pos.x() - self._press_pos.x()
        dy = global_pos.y() - self._press_pos.y()

        edge = self._resize_edge
        g = self._start_geom
        x0, y0, w0, h0 = g.x(), g.y(), g.width(), g.height()
        min_w, max_w = self._MIN_WIDTH + 8, self._MAX_WIDTH + 8
        min_h, max_h = self._MIN_HEIGHT + 8, self._MAX_HEIGHT + 8

        new_x, new_y, new_w, new_h = x0, y0, w0, h0

        if "r" in edge:
            new_w = max(min_w, min(max_w, w0 + dx))
        elif "l" in edge:
            proposed_w = max(min_w, min(max_w, w0 - dx))
            new_x = x0 + (w0 - proposed_w)
            new_w = proposed_w

        if "b" in edge:
            new_h = max(min_h, min(max_h, h0 + dy))
        elif "t" in edge:
            proposed_h = max(min_h, min(max_h, h0 - dy))
            new_y = y0 + (h0 - proposed_h)
            new_h = proposed_h

        self.setGeometry(new_x, new_y, new_w, new_h)

    # ── Click & Drag & Resize event filter ────────────────

    def _install_click_filter(self, widget: QWidget) -> None:
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            if child is not self._btn_close and not isinstance(child, (QScrollBar, QScrollArea)):
                child.setMouseTracking(True)
                child.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, (QScrollBar, QScrollArea)) or obj is self._btn_close:
            return False

        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            if self._scroll_area is not None:
                sb_v = self._scroll_area.verticalScrollBar()
                if sb_v is not None and sb_v.isVisible():
                    sb_global_rect = QRect(sb_v.mapToGlobal(QPoint(0, 0)), sb_v.size())
                    if sb_global_rect.contains(event.globalPos()):
                        return False

        if event.type() == QEvent.MouseMove:
            pos_local = self.mapFromGlobal(event.globalPos())
            if not event.buttons():
                edge = self._detect_resize_edge(pos_local)
                self._update_cursor_for_edge(edge)
            elif event.buttons() & Qt.LeftButton and self._press_pos is not None:
                if self._resize_edge:
                    self._perform_resize(event.globalPos())
                    return True
                else:
                    dist = (event.globalPos() - self._press_pos).manhattanLength()
                    if dist > 5 or self._is_dragging:
                        self._is_dragging = True
                        self.setCursor(Qt.ClosedHandCursor)
                        self.move(event.globalPos() - self._drag_offset)
                        return True
        elif event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                pos_local = self.mapFromGlobal(event.globalPos())
                self._resize_edge = self._detect_resize_edge(pos_local)
                self._press_pos = event.globalPos()
                self._start_geom = self.geometry()
                self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
                self._is_dragging = False
        elif event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self._resize_edge = None
                self.setCursor(Qt.OpenHandCursor)
                self._is_dragging = False
                self._press_pos = None
        return super().eventFilter(obj, event)

    # ── Mouse Click & Drag inside ─────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._resize_edge = self._detect_resize_edge(event.pos())
            self._press_pos = event.globalPos()
            self._start_geom = self.geometry()
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if not event.buttons():
            edge = self._detect_resize_edge(event.pos())
            self._update_cursor_for_edge(edge)
        elif event.buttons() & Qt.LeftButton and self._press_pos is not None:
            if self._resize_edge:
                self._perform_resize(event.globalPos())
                event.accept()
            else:
                dist = (event.globalPos() - self._press_pos).manhattanLength()
                if dist > 5 or self._is_dragging:
                    self._is_dragging = True
                    self.setCursor(Qt.ClosedHandCursor)
                    self.move(event.globalPos() - self._drag_offset)
                    event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._resize_edge = None
            self.setCursor(Qt.OpenHandCursor)
            self._is_dragging = False
            self._press_pos = None
            event.accept()

    # ── Keyboard ──────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._fade_out_and_close()
        else:
            super().keyPressEvent(event)

    # ── Rounded card background with true alpha ──────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        path = QPainterPath()
        r = self.rect().adjusted(4, 3, -4, -4)
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 10, 10)

        if self._is_loading:
            bg = QColor(25, 30, 45, int(255 * self._BG_OPACITY))
        elif self._is_error:
            bg = QColor(40, 20, 20, int(255 * self._BG_OPACITY))
        else:
            bg = QColor(28, 28, 36, int(255 * self._BG_OPACITY))

        painter.fillPath(path, bg)

        painter.setPen(QColor(255, 255, 255, 15))
        painter.drawPath(path)
        painter.end()

    # ── Positioning ──────────────────────────────────────

    def _position_near_anchor(self) -> None:
        if self._anchor is None:
            cursor = QCursor.pos()
            screen = self._screen_at(cursor)
        else:
            a = self._anchor
            screen = self._screen_at(QPoint(a.center().x(), a.center().y()))

        sg = screen.availableGeometry()

        self._fit_and_adjust_size()
        ps = self.size()

        if self._anchor is None:
            x = sg.x() + (sg.width() - ps.width()) // 2
            y = sg.y() + (sg.height() - ps.height()) // 2
        else:
            a = self._anchor
            x = a.left() + (a.width() - ps.width()) // 2
            y = a.bottom() + self._MARGIN

            if y + ps.height() > sg.y() + sg.height():
                y = a.top() - ps.height() - self._MARGIN

        min_x = sg.x() + self._MARGIN
        max_x = sg.x() + sg.width() - ps.width() - self._MARGIN
        if max_x < min_x:
            max_x = min_x
        x = max(min_x, min(x, max_x))

        min_y = sg.y() + self._MARGIN
        max_y = sg.y() + sg.height() - ps.height() - self._MARGIN
        if max_y < min_y:
            max_y = min_y
        y = max(min_y, min(y, max_y))

        self.move(x, y)

    @staticmethod
    def _screen_at(pos: QPoint):
        for s in QApplication.screens():
            if s.geometry().contains(pos):
                return s
        return QApplication.primaryScreen()


# ── Public helper for displaying result / toast ──────────

def show_result(
    source_text: str,
    translated_text: str,
    anchor: QRect | None = None,
    *,
    is_error: bool = False,
    tray_icon=None,
    existing_popup: ResultPopup | None = None,
) -> ResultPopup | None:
    """Display translation result or error via popup or Windows toast according
    to config.NOTIFICATION_TYPE.
    """
    if config.NOTIFICATION_TYPE == "windows_toast":
        if existing_popup is not None and not existing_popup._closing:
            existing_popup.hide()
            existing_popup.deleteLater()

        title = "Ошибка перевода" if is_error else "Перевод"
        msg = translated_text

        if tray_icon is not None and hasattr(tray_icon, "showMessage"):
            icon = QSystemTrayIcon.Warning if is_error else QSystemTrayIcon.Information
            tray_icon.showMessage(title, msg, icon, 5000)
        else:
            try:
                from plyer import notification
                notification.notify(title=title, message=msg, timeout=5)
            except Exception:
                pass

        return None
    else:
        if existing_popup is not None and not existing_popup._closing:
            existing_popup.update_content(source_text, translated_text, is_error=is_error)
            return existing_popup
        else:
            popup = ResultPopup(source_text, translated_text, anchor, is_error=is_error)
            popup.show()
            return popup
