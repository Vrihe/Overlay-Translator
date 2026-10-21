"""
ui/result_popup.py — lightweight floating popup and notification helper.

Design goals:
  • Non-intrusive — compact, near-opaque HUD card (1 px accent frame), instant appearance
  • Resizable & Draggable — stretchable from the left, right and bottom edges and bottom corners
    (the top edge is the drag handle; max 850x550, min 300x80);
    a size set by hand is saved (``config.POPUP_SIZE``) and reused by later updates,
    popups and launches (text wraps to it)
  • Streaming — partial text goes to the body (``show_partial``), the header keeps
    "Переводим…"
  • Clean header with icon buttons (speak / copy / close) — window remains open on focus
    loss or window body clicks
  • Strict screen bounds — wrapped in QScrollArea, never exceeds monitor bounds
  • Dismissable — close button, Escape key, or 10s fallback timeout
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QScrollBar, QFrame, QApplication, QSystemTrayIcon,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QEvent, QSize,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import QPainter, QPen, QCursor

import ctypes
import sys

import config
from i18n import tr
from ui import icons, theme


#: SetWindowDisplayAffinity: shown on screen, left out of every capture.
_WDA_EXCLUDEFROMCAPTURE = 0x11


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
    _ICON_SIZE = 14               # header icon buttons


    def __init__(
        self,
        source_text: str = "",
        translated_text: str = "",
        anchor: QRect | None = None,
        *,
        is_error: bool = False,
        is_loading: bool = False,
        notice: str = "",
        parent=None,
    ):
        super().__init__(parent)

        self._translated = translated_text
        self._anchor = anchor
        self._is_error = is_error
        self._is_loading = is_loading
        self._notice = notice
        self._closing = False
        self._scroll_area: QScrollArea | None = None
        self._btn_close: QPushButton | None = None
        self._stream_label: QLabel | None = None

        self._dots_count = 3
        self._dots_timer: QTimer | None = None

        self._press_pos: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._start_geom: QRect | None = None
        self._is_dragging = False
        self._resize_edge: str | None = None
        self._resized = False
        self._moved_by_user = False

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
        # Opaque on purpose: a translucent (UpdateLayeredWindow) window cannot be kept
        # out of screen captures, see _exclude_from_capture().
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setWindowOpacity(1.0)  # Instant show — no delay

    # ── Show ─────────────────────────────────────────────

    def show(self) -> None:
        super().show()
        self._exclude_from_capture()
        self.raise_()
        self.activateWindow()
        self.setFocus()

        if not self._is_loading:
            self._start_auto_timer()

    def _exclude_from_capture(self) -> None:
        """Keep the popup out of screen captures (Windows 10 2004+).

        Live monitoring and OCR capture the screen: a popup lying over the watched
        region would count as a change and be read as text, in a loop. The window must
        be opaque for this (the call fails on WA_TranslucentBackground windows).
        """
        if sys.platform != "win32":
            return
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), _WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass  # older Windows: the popup stays visible to captures

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
            layout.setContentsMargins(0, 0, 0, 0)  # the card fills the window: no invisible border eating clicks
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

        from translate.domain_manager import display_name_of, load_domain_profile
        domain_display_name = display_name_of(load_domain_profile(config.ACTIVE_DOMAIN))
        p = theme.current()

        if self._is_loading:
            self._loading_label = QLabel(
                tr("Переводим ({context})...", context=domain_display_name)
            )
            self._loading_label.setTextFormat(Qt.PlainText)
            self._loading_label.setFont(theme.body_font(9, medium=True, spacing=106))
            self._loading_label.setStyleSheet(f"color: {p.text_soft}; background: transparent;")
            header_row.addWidget(self._loading_label)
            self._start_dots_animation()
        else:
            title_text = tr("Ошибка") if self._is_error else tr("Перевод")
            header_lbl = QLabel(title_text.upper())
            header_lbl.setFont(theme.display_font(9.5, spacing=118))
            header_lbl.setStyleSheet(
                f"color: {p.error if self._is_error else p.accent}; background: transparent;"
            )
            header_row.addWidget(header_lbl)

            domain_badge = QLabel(f"·  {domain_display_name}")
            domain_badge.setTextFormat(Qt.PlainText)
            domain_badge.setStyleSheet(theme.text_css(p.muted, 8.5))
            header_row.addWidget(domain_badge)

        header_row.addStretch()

        # C1 & D3: Copy and TTS buttons (visible only in final, non-error state)
        if not self._is_loading and not self._is_error and self._translated:
            # D3: Speech synthesis button
            self._btn_tts = self._icon_button("speaker", tr("Озвучить перевод"))
            self._btn_tts.clicked.connect(self._on_speak_translation)
            header_row.addWidget(self._btn_tts)

            # C1: Copy to clipboard button
            self._btn_copy = self._icon_button("copy", tr("Скопировать перевод"))
            self._btn_copy.clicked.connect(self._on_copy_translation)
            header_row.addWidget(self._btn_copy)

        self._btn_close = self._icon_button("close", tr("Закрыть окно"), danger=True)
        self._btn_close.clicked.connect(self._fade_out_and_close)
        header_row.addWidget(self._btn_close)

        card_layout.addLayout(header_row)

        # Scrollable container for text
        self._scroll_area = QScrollArea(self._card)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + theme.scrollbar_css()
        )

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)
        content_layout.setAlignment(Qt.AlignTop)

        if self._is_loading:
            # Live streaming text (show_partial); hidden until the first chunk.
            self._stream_label = self._make_label("", size=11, color=p.text, bold=True)
            self._stream_label.setVisible(False)
            content_layout.addWidget(self._stream_label)
        else:
            self._stream_label = None
            if self._is_error:
                err = self._make_label(self._translated, size=10.5, color=p.error)
                content_layout.addWidget(err)
            else:
                tl = self._make_label(self._translated, size=11, color=p.text, bold=True)
                content_layout.addWidget(tl)

            # Backend notice (e.g. local NLLB model unavailable → API was used).
            # Kept out of self._translated so copy/TTS still yield the clean text.
            if self._notice:
                note = self._make_label(f"⚠ {self._notice}", size=8, color=p.warn)
                content_layout.addWidget(note)

        self._scroll_area.setWidget(scroll_content)
        card_layout.addWidget(self._scroll_area)
        layout.addWidget(self._card)

    def _icon_button(self, name: str, tooltip: str, *, danger: bool = False) -> QPushButton:
        p = theme.current()
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        btn.setIcon(icons.icon(name, p.muted, self._ICON_SIZE,
                               active_color=p.error if danger else p.text_soft))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(theme.btn_icon(danger=danger))
        return btn

    @staticmethod
    def _make_label(text: str, *, size: float = 12, color: str = "", bold: bool = False) -> QLabel:
        label = QLabel(text)
        # OCR text and LLM output are untrusted: never let Qt render them as HTML.
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setStyleSheet(
            theme.text_css(color or theme.current().text, size, bold=bold) + " padding: 2px 0;"
        )
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ── TTS Speech synthesis (D3) ────────────────────────

    def _on_speak_translation(self) -> None:
        """D3: Speak translated text via background TTS engine."""
        if not self._translated:
            return
        try:
            from tts.engine import speak
            speak(self._translated)
        except Exception:
            pass

    # ── Copy to clipboard (C1) ───────────────────────────

    def _on_copy_translation(self) -> None:
        """C1: Copy the translated text to clipboard with visual feedback."""
        if not self._translated:
            return
        QApplication.clipboard().setText(self._translated)
        btn = getattr(self, "_btn_copy", None)
        if btn is None:
            return
        btn.setIcon(icons.icon("check", theme.current().ok, self._ICON_SIZE))
        QTimer.singleShot(1500, lambda: self._reset_copy_btn(btn))

    def _reset_copy_btn(self, btn: QPushButton) -> None:
        """Restore copy button to default state after feedback delay."""
        try:
            p = theme.current()
            btn.setIcon(icons.icon("copy", p.muted, self._ICON_SIZE, active_color=p.text_soft))
        except RuntimeError:
            pass  # widget already deleted

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
        from translate.domain_manager import display_name_of, load_domain_profile
        domain_display_name = display_name_of(load_domain_profile(config.ACTIVE_DOMAIN))
        self._dots_count = (self._dots_count % 3) + 1
        dots = "." * self._dots_count
        self._loading_label.setText(tr("Переводим ({context})", context=domain_display_name) + dots)

    # ── Streaming preview ────────────────────────────────

    def show_partial(self, text: str) -> None:
        """Show the translation as it streams in (loading state only)."""
        if self._closing or not self._is_loading or self._stream_label is None:
            return
        self._stream_label.setText(text)
        if not self._stream_label.isVisible():
            self._stream_label.setVisible(True)
            self._install_click_filter(self._stream_label)
        if self.saved_size() is None:
            saved_pos = self.pos()
            self._fit_and_adjust_size()
            self.move(saved_pos)
            self._step_aside_if_covering()
        if self._scroll_area is not None:  # follow the newest text
            bar = self._scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())

    # ── In-place content update ──────────────────────────

    def update_content(self, source_text: str, translated_text: str, *,
                       is_error: bool = False, notice: str = "", activate: bool = True) -> None:
        """Update popup content from loading state to final result in-place,
        fitting the window snugly to the translated content size.

        ``activate=False`` (live monitoring updates) keeps it on top without taking
        the keyboard focus from the game or browser being watched.
        """
        if self._closing:
            return

        if self._dots_timer is not None:
            self._dots_timer.stop()

        self._is_loading = False
        self._is_error = is_error
        self._translated = translated_text
        self._notice = notice

        saved_pos = self.pos()

        self._build_ui()
        self._install_click_filter(self._card)
        self._fit_and_adjust_size()
        self.move(saved_pos)
        self._step_aside_if_covering()

        self._start_auto_timer()

        self.raise_()
        if activate:
            self.activateWindow()
            self.setFocus()
        self.update()

    def _fit_and_adjust_size(self) -> None:
        """Size the window: the size the user dragged to, otherwise fit the content."""
        self.setMinimumSize(self._MIN_WIDTH, self._MIN_HEIGHT)
        self.setMaximumSize(self._MAX_WIDTH, self._MAX_HEIGHT)
        if self._scroll_area is not None:
            self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        remembered = self.saved_size()
        if remembered is not None:
            self.resize(remembered)  # labels word-wrap to it; the scroll area takes the rest
            return

        self.layout().activate()
        self._card.layout().activate()
        if self._scroll_area is not None and self._scroll_area.widget() is not None:
            self._scroll_area.widget().layout().activate()

        hint = self.sizeHint()
        w = max(self._MIN_WIDTH, min(self._MAX_WIDTH, hint.width()))
        h = max(self._MIN_HEIGHT, min(self._MAX_HEIGHT, hint.height()))
        self.resize(w, h)

        # QScrollArea's size hint ignores word wrap: grow to the wrapped text height.
        content = self._scroll_area.widget() if self._scroll_area is not None else None
        if content is not None:
            self.layout().activate()
            viewport = self._scroll_area.viewport()
            needed = (content.heightForWidth(viewport.width()) if content.hasHeightForWidth()
                      else content.sizeHint().height())
            if needed > viewport.height():
                h = min(self._MAX_HEIGHT, self.height() + needed - viewport.height())
                self.resize(w, h)

    # ── Edge detection & Mouse Resizing / Dragging ────────

    def _detect_resize_edge(self, pos: QPoint) -> str | None:
        r = self.rect()
        m = self._RESIZE_MARGIN
        x, y, w, h = pos.x(), pos.y(), r.width(), r.height()

        # No top edge: it is the header, so grabbing it always moves the window.
        on_right = (x >= w - m)
        on_bottom = (y >= h - m)
        on_left = (x <= m)

        if on_right and on_bottom:
            return "br"
        elif on_left and on_bottom:
            return "bl"
        elif on_right:
            return "r"
        elif on_bottom:
            return "b"
        elif on_left:
            return "l"
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
        min_w, max_w = self._MIN_WIDTH, self._MAX_WIDTH
        min_h, max_h = self._MIN_HEIGHT, self._MAX_HEIGHT

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
        self._resized = True

    # ── Saved size (config.POPUP_SIZE) ───────────────────

    @classmethod
    def saved_size(cls) -> QSize | None:
        """The size the user dragged a popup to, clamped to the limits; None = fit text."""
        return cls._parse_size(getattr(config, "POPUP_SIZE", None))

    @classmethod
    def _parse_size(cls, value) -> QSize | None:
        try:
            w, h = (int(v) for v in value)
        except (TypeError, ValueError):
            return None  # None / malformed hand-edited value
        w = max(cls._MIN_WIDTH, min(cls._MAX_WIDTH, w))
        h = max(cls._MIN_HEIGHT, min(cls._MAX_HEIGHT, h))
        return QSize(w, h)

    def _finish_resize(self) -> None:
        """Persist the size once a resize drag ends (not on every mouse move)."""
        if not self._resized:
            return
        self._resized = False
        try:
            config.POPUP_SIZE = [self.width(), self.height()]
        except Exception:
            pass  # settings file not writable: the size still applies to this popup

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
                elif self._drag_move(event.globalPos()):
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
                self._finish_resize()
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
            elif self._drag_move(event.globalPos()):
                event.accept()

    def _drag_move(self, global_pos: QPoint) -> bool:
        """Move the window for a left-button drag; False until the 5 px threshold."""
        if not self._is_dragging:
            if (global_pos - self._press_pos).manhattanLength() <= 5:
                return False
            self._moved_by_user = True
            # The OS move loop tracks the cursor smoothly even while Python is busy
            # and skips a repaint of the translucent window per mouse move. It eats
            # the button release, so the press state is cleared right here.
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                self._press_pos = None
                return True
            self._is_dragging = True
            self.setCursor(Qt.ClosedHandCursor)
        self.move(global_pos - self._drag_offset)
        return True

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._finish_resize()
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

    # ── Square HUD card ──────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(self.rect(), theme.qcolor("bg"))

        if self._is_loading:
            border = theme.qcolor("dim")
        elif self._is_error:
            border = theme.qcolor("error")
        else:
            border = theme.qcolor("accent")
        painter.setPen(QPen(border, 1))
        painter.drawRect(r)
        painter.end()

    # ── Positioning ──────────────────────────────────────

    def _position_near_anchor(self) -> None:
        self._fit_and_adjust_size()
        self.move(self._place(self.size(), self._anchor, self._screen_rect(),
                              self._app_window_rects(), self._MARGIN))

    def _step_aside_if_covering(self) -> None:
        """After the popup grew in place, move it off an app window it now covers.

        A popup the user dragged stays where they put it.
        """
        if self._moved_by_user:
            return
        avoid = self._app_window_rects()
        if any(self.frameGeometry().intersects(r) for r in avoid):
            self.move(self._place(self.size(), self._anchor, self._screen_rect(),
                                  avoid, self._MARGIN))

    def _screen_rect(self) -> QRect:
        if self._anchor is None:
            screen = self._screen_at(QCursor.pos())
        else:
            screen = self._screen_at(self._anchor.center())
        return screen.availableGeometry()

    def _app_window_rects(self) -> list:
        """Visible windows and dialogs of the app (the main window first of all)."""
        return [w.frameGeometry() for w in QApplication.topLevelWidgets()
                if w is not self and w.isVisible() and not w.isMinimized()
                and w.windowType() in (Qt.Window, Qt.Dialog)]

    @staticmethod
    def _place(size: QSize, anchor: QRect | None, screen: QRect, avoid: list,
               margin: int) -> QPoint:
        """Top-left for a popup of *size*.

        Preferred spot: under the anchor (above it when there is no room below),
        centred on it; without an anchor, the screen centre. When that spot covers
        one of the *avoid* windows, the nearest spot that covers neither them nor
        the anchor is used; if the screen has none, the preferred spot stays.
        """
        w, h = size.width(), size.height()
        max_x = max(screen.x() + margin, screen.x() + screen.width() - w - margin)
        max_y = max(screen.y() + margin, screen.y() + screen.height() - h - margin)

        def clamp(x: int, y: int) -> QPoint:
            return QPoint(max(screen.x() + margin, min(x, max_x)),
                          max(screen.y() + margin, min(y, max_y)))

        if anchor is None:
            xs = [screen.x() + (screen.width() - w) // 2]
            ys = [screen.y() + (screen.height() - h) // 2]
        else:
            xs = [anchor.left() + (anchor.width() - w) // 2]
            below, above = anchor.bottom() + margin, anchor.top() - h - margin
            ys = [below, above] if below + h <= screen.y() + screen.height() else [above, below]
        preferred = clamp(xs[0], ys[0])

        def covers_window(p: QPoint) -> bool:
            return any(QRect(p, size).intersects(o) for o in avoid)

        def is_free(p: QPoint) -> bool:
            return not covers_window(p) and (anchor is None or not QRect(p, size).intersects(anchor))

        if not covers_window(preferred):
            return preferred

        for o in avoid:  # beside / above / below each window in the way
            xs += [o.left() - w - margin, o.right() + 1 + margin]
            ys += [o.top() - h - margin, o.bottom() + 1 + margin]
        spots = {(p.x(), p.y()) for p in (clamp(x, y) for x in xs for y in ys)}
        free = [QPoint(x, y) for x, y in spots if is_free(QPoint(x, y))]
        if not free:
            return preferred
        return min(free, key=lambda p: ((p - preferred).manhattanLength(), p.y(), p.x()))

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
    notice: str = "",
    tray_icon=None,
    existing_popup: ResultPopup | None = None,
    activate: bool = True,
) -> ResultPopup | None:
    """Display translation result or error via popup or Windows toast according
    to config.NOTIFICATION_TYPE. ``activate=False``: an open popup is updated
    without taking the keyboard focus (live monitoring).
    """
    if config.NOTIFICATION_TYPE == "windows_toast":
        if existing_popup is not None and not existing_popup._closing:
            existing_popup.hide()
            existing_popup.deleteLater()

        title = tr("Ошибка перевода") if is_error else tr("Перевод")
        msg = f"{translated_text}\n\n⚠ {notice}" if notice else translated_text

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
            existing_popup.update_content(
                source_text, translated_text, is_error=is_error, notice=notice, activate=activate
            )
            return existing_popup
        else:
            popup = ResultPopup(source_text, translated_text, anchor,
                                is_error=is_error, notice=notice)
            popup.show()
            return popup
