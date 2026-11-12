"""
ui/result_popup.py — lightweight floating popup and notification helper.

Design goals:
  • Non-intrusive — a HUD card that never takes the keyboard focus, is translucent
    (Settings → Popup) with a dim frame until the cursor is over it, and can hide its header
    ("compact") or let clicks through unless Alt is held (ui/overlay_behavior.py)
  • Resizable & Draggable — stretchable from the left, right and bottom edges and bottom corners
    (the top edge is the drag handle; max 850x550, min 300x44); without a saved size
    the height fits the wrapped text exactly;
    a size set by hand is saved (``config.POPUP_SIZE``) and reused by later updates,
    popups and launches (text wraps to it)
  • Streaming — partial text goes to the body (``show_partial``), the header keeps
    "Переводим…"
  • Clean header with icon buttons (speak / copy / close) — window remains open on focus
    loss or window body clicks
  • Strict screen bounds — wrapped in QScrollArea, never exceeds monitor bounds
  • Dismissable — close button, Escape (once the popup was clicked: it has no focus
    before that), or the auto-hide timeout (Settings → Popup, 3 s – 10 min, read at every start)
"""

import ctypes
import sys

from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QCursor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import config
from i18n import tr
from ui import icons, overlay_behavior, theme

#: SetWindowDisplayAffinity: shown on screen, left out of every capture.
_WDA_EXCLUDEFROMCAPTURE = 0x11


class ResultPopup(QWidget):
    #: The header's stop button: end the live monitoring that keeps updating this popup.
    stop_monitoring_clicked = pyqtSignal()
    #: Where the user dragged the popup to (top-left), while and after the drag.
    moved_by_user = pyqtSignal(QPoint)

    """Compact floating popup showing source text and its translation, or loading status."""

    _MIN_WIDTH = 300
    _MAX_WIDTH = 850
    _MIN_HEIGHT = 44  # one line of text without the header (compact mode)
    _MAX_HEIGHT = 550
    _RESIZE_MARGIN = 8
    _FADE_DURATION = 150  # ms for smooth fade-out on close
    _MARGIN = 10  # gap between popup and selection edge
    _ICON_SIZE = 14  # header icon buttons
    _FRESH_MS = 1500  # a new result keeps the accent frame this long

    def __init__(
        self,
        source_text: str = "",
        translated_text: str = "",
        anchor: QRect | None = None,
        *,
        is_error: bool = False,
        is_loading: bool = False,
        notice: str = "",
        blocks: list[tuple[str, str]] | None = None,
        parent=None,
    ):
        super().__init__(parent)

        self._translated = translated_text
        # Translated blocks of one region, newest first, as (time stamp, text): with more
        # than one, each gets a separator and the older ones are dimmed below the newest.
        self._blocks = blocks or []
        # Widgets from the top through the newest block: the window fits these, never
        # the older blocks, so the history scrolls instead of growing the popup.
        self._fit_widgets: list[QWidget] = []
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
        self._monitoring = False  # updated by live monitoring: offer its stop button
        # The cursor is over the popup (click-through: with Alt held): solid, header shown.
        self._engaged = False
        self._header: QWidget | None = None
        # A result that just arrived: the accent frame for a moment, then the dim one.
        self._fresh = not is_loading
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setSingleShot(True)
        self._fresh_timer.timeout.connect(self._on_fresh_expired)
        self._watcher = overlay_behavior.EngageWatcher(self, self._on_engaged_changed)

        self._setup_window()
        self._build_ui()
        self._position_near_anchor()
        self._install_click_filter(self)

    # ── Window setup ─────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        # No WA_TranslucentBackground on purpose: such (UpdateLayeredWindow) windows cannot
        # be kept out of screen captures, see _exclude_from_capture(). Whole-window opacity
        # (setWindowOpacity) is fine.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        # Never take the keyboard from the game or stream the user is in; a click on
        # the popup still activates it (Esc, text selection).
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setWindowOpacity(overlay_behavior.rest_opacity())

    # ── Show ─────────────────────────────────────────────

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._moved_by_user:  # the OS move loop moves the window: report every step
            self.moved_by_user.emit(self.pos())

    def place_at(self, pos: QPoint) -> None:
        """Open where the user last dragged a popup of the same region, if still on a screen."""
        if QApplication.screenAt(pos + QPoint(20, 20)) is None:
            return  # that monitor is gone: keep the usual placement
        self.move(pos)
        self._moved_by_user = True  # never "step aside" from a place the user chose

    def show(self) -> None:
        super().show()
        self._exclude_from_capture()
        self.raise_()
        self._watcher.start()

        if not self._is_loading:
            self._start_auto_timer()
            self._fresh_timer.start(self._FRESH_MS)

    def hideEvent(self, event) -> None:
        self._watcher.stop()
        super().hideEvent(event)

    # ── Unobtrusive behaviour (ui/overlay_behavior.py) ───

    def _on_engaged_changed(self, engaged: bool) -> None:
        self._engaged = engaged
        self._sync_header()
        self.update()  # the frame: accent while engaged, dim at rest

    def _on_fresh_expired(self) -> None:
        self._fresh = False
        self.update()

    def _header_wanted(self) -> bool:
        """Compact mode hides the header (title and buttons) until the popup is engaged."""
        return self._is_loading or self._engaged or not overlay_behavior.compact()

    def _header_delta(self) -> int:
        """Height the header adds to the card."""
        if self._header is None:
            return 0
        return self._header.sizeHint().height() + self._card.layout().spacing()

    def _sync_header(self) -> None:
        """Show / hide the header; the window grows upwards so the text does not move."""
        if self._header is None or self._closing or self._header.isHidden() != self._header_wanted():
            return
        show = self._header_wanted()
        delta = self._header_delta()
        g = self.geometry()
        height = min(self._MAX_HEIGHT, g.height() + delta) if show else max(self._MIN_HEIGHT, g.height() - delta)
        self._header.setVisible(show)
        self.setGeometry(g.x(), g.y() - (height - g.height()), g.width(), height)

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

    def _keeps_open(self) -> bool:
        """Live monitoring with "keep open" on: the auto-hide timer does not run."""
        return self._monitoring and bool(getattr(config, "LIVE_POPUP_KEEP_OPEN", True))

    def _start_auto_timer(self) -> None:
        if hasattr(self, "_auto_timer") and self._auto_timer.isActive():
            self._auto_timer.stop()
        if self._keeps_open():
            return
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._fade_out_and_close)
        self._auto_timer.start(self.auto_close_ms())

    @staticmethod
    def auto_close_ms() -> int:
        """Settings → Popup → auto-hide, read at every start so a change applies at once."""
        try:
            seconds = int(config.POPUP_TIMEOUT_SEC or 10)
        except (TypeError, ValueError):
            seconds = 10  # hand-edited settings.json
        return max(3, min(600, seconds)) * 1000

    # ── Close with fast fade-out ─────────────────────────

    def _fade_out_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True

        if self._dots_timer is not None and self._dots_timer.isActive():
            self._dots_timer.stop()

        if hasattr(self, "_auto_timer") and self._auto_timer.isActive():
            self._auto_timer.stop()
        self._watcher.stop()  # the fade owns the opacity from here

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InCubic)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._fit_widgets = []  # refilled by _add_blocks; the old widgets are deleted below
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

        # Header bar: Title/loading status on left + Close button ("✕") on right.
        # A widget of its own so that compact mode can hide it (_sync_header).
        self._header = QWidget(self._card)
        self._header.setStyleSheet("background: transparent;")
        header_row = QHBoxLayout(self._header)
        header_row.setContentsMargins(0, 0, 0, 2)
        header_row.setSpacing(6)

        from translate.domain_manager import display_name_of, load_domain_profile

        domain_display_name = display_name_of(load_domain_profile(config.ACTIVE_DOMAIN))
        p = theme.current()

        if self._is_loading:
            self._loading_label = QLabel(tr("Переводим ({context})...", context=domain_display_name))
            self._loading_label.setTextFormat(Qt.PlainText)
            self._loading_label.setFont(theme.body_font(9, medium=True, spacing=106))
            self._loading_label.setStyleSheet(f"color: {p.text_soft}; background: transparent;")
            header_row.addWidget(self._loading_label)
            self._start_dots_animation()
        else:
            title_text = tr("Ошибка") if self._is_error else tr("Перевод")
            header_lbl = QLabel(title_text.upper())
            header_lbl.setFont(theme.display_font(9.5, spacing=118))
            header_lbl.setStyleSheet(f"color: {p.error if self._is_error else p.accent}; background: transparent;")
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

        # Live monitoring keeps updating this popup: let it be stopped right here.
        self._btn_stop_monitoring = self._icon_button("stop", tr("Остановить мониторинг"), danger=True)
        self._btn_stop_monitoring.clicked.connect(self._on_stop_monitoring)
        self._btn_stop_monitoring.setVisible(self._monitoring)
        header_row.addWidget(self._btn_stop_monitoring)

        self._btn_close = self._icon_button("close", tr("Закрыть окно"), danger=True)
        self._btn_close.clicked.connect(self._fade_out_and_close)
        header_row.addWidget(self._btn_close)

        card_layout.addWidget(self._header)
        self._header.setVisible(self._header_wanted())

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
                self._add_blocks(content_layout, p)

            # Backend notice (e.g. local NLLB model unavailable → API was used).
            # Kept out of self._translated so copy/TTS still yield the clean text.
            if self._notice:
                note = self._make_label(f"⚠ {self._notice}", size=8, color=p.warn)
                if self._is_error or len(self._blocks) < 2:
                    content_layout.addWidget(note)
                else:  # right under the newest block, above the history
                    content_layout.insertWidget(len(self._fit_widgets), note)
                    self._fit_widgets.append(note)

        self._scroll_area.setWidget(scroll_content)
        card_layout.addWidget(self._scroll_area)
        layout.addWidget(self._card)

    def _add_blocks(self, content_layout: QVBoxLayout, p) -> None:
        """The translation; with a region's history, newest first under time separators."""
        self._fit_widgets = []
        if len(self._blocks) < 2:
            content_layout.addWidget(self._make_label(self._translated, size=11, color=p.text, bold=True))
            return
        for index, (stamp, text) in enumerate(self._blocks):
            newest = index == 0
            separator = self._block_separator(stamp, p)
            label = self._make_label(text, size=11 if newest else 10, color=p.text if newest else p.muted, bold=newest)
            content_layout.addWidget(separator)
            content_layout.addWidget(label)
            if newest:
                self._fit_widgets = [separator, label]

    @staticmethod
    def _block_separator(stamp: str, p) -> QWidget:
        """A thin rule with the block's time: ``─ 21:42:10 ─────────``."""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        time_label = QLabel(stamp)
        time_label.setTextFormat(Qt.PlainText)
        time_label.setStyleSheet(theme.text_css(p.muted, 8))
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {p.line}; border: none;")
        layout.addWidget(time_label)
        layout.addWidget(rule, 1)
        return row

    def _icon_button(self, name: str, tooltip: str, *, danger: bool = False) -> QPushButton:
        p = theme.current()
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        btn.setIcon(icons.icon(name, p.muted, self._ICON_SIZE, active_color=p.error if danger else p.text_soft))
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
        label.setStyleSheet(theme.text_css(color or theme.current().text, size, bold=bold) + " padding: 2px 0;")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ── TTS Speech synthesis (D3) ────────────────────────

    def set_monitoring(self, active: bool) -> None:
        """Show the stop button while live monitoring updates this popup."""
        was_kept_open = self._keeps_open()
        self._monitoring = active
        btn = getattr(self, "_btn_stop_monitoring", None)
        if btn is not None:
            btn.setVisible(active)
        if self._keeps_open():
            if hasattr(self, "_auto_timer"):
                self._auto_timer.stop()
        elif was_kept_open and not self._is_loading and not self._closing:
            self._start_auto_timer()  # monitoring stopped: the usual auto-hide again

    def _on_stop_monitoring(self) -> None:
        self.set_monitoring(False)
        self.stop_monitoring_clicked.emit()

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

    def update_content(
        self,
        source_text: str,
        translated_text: str,
        *,
        is_error: bool = False,
        notice: str = "",
        blocks: list[tuple[str, str]] | None = None,
    ) -> None:
        """Update popup content from loading state to final result in-place,
        fitting the window snugly to the translated content size.

        The popup stays on top but is never activated: the keyboard focus stays with
        the game or browser the user is in.
        """
        if self._closing:
            return

        if self._dots_timer is not None:
            self._dots_timer.stop()

        # A result replacing a result (live monitoring) keeps where the reader scrolled to;
        # the first result after "Переводим…" starts at the top as before.
        scroll = self._scroll_state() if not self._is_loading else None

        self._is_loading = False
        self._is_error = is_error
        self._translated = translated_text
        self._notice = notice
        self._blocks = [] if is_error else (blocks or [])
        if len(self._blocks) > 1:
            scroll = None  # the newest block is on top: show it, not the old scroll spot

        saved_pos = self.pos()

        self._build_ui()
        self._install_click_filter(self._card)
        self._fit_and_adjust_size()
        self.move(saved_pos)
        self._step_aside_if_covering()
        if scroll is not None:
            # After the rebuilt layout has its final size, or the range is still empty.
            QTimer.singleShot(0, lambda: self._restore_scroll(scroll))

        self._start_auto_timer()
        self._fresh = True
        self._fresh_timer.start(self._FRESH_MS)

        self.raise_()
        self.update()

    def _scroll_state(self) -> tuple[int, bool] | None:
        """``(value, at_bottom)`` of the text's scroll bar, None without one."""
        if self._scroll_area is None:
            return None
        bar = self._scroll_area.verticalScrollBar()
        return bar.value(), bar.maximum() > 0 and bar.value() >= bar.maximum() - 2

    def _restore_scroll(self, state: tuple[int, bool]) -> None:
        """Back where the reader was; at the bottom it follows the newest lines."""
        if self._closing or self._scroll_area is None:
            return
        value, at_bottom = state
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum() if at_bottom else min(value, bar.maximum()))

    def _fit_and_adjust_size(self) -> None:
        """Size the window: the size the user dragged to, otherwise fit the content."""
        self.setMinimumSize(self._MIN_WIDTH, self._MIN_HEIGHT)
        self.setMaximumSize(self._MAX_WIDTH, self._MAX_HEIGHT)
        if self._scroll_area is not None:
            self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        remembered = self.saved_size()
        if remembered is not None:
            # Labels word-wrap to it; the scroll area takes the rest. The saved size is
            # the popup at rest: a compact popup showing its header is that much taller.
            extra = self._header_delta() if self._compact_header_shown() else 0
            self.resize(remembered.width(), min(self._MAX_HEIGHT, remembered.height() + extra))
            return

        self.layout().activate()
        self._card.layout().activate()
        if self._scroll_area is not None and self._scroll_area.widget() is not None:
            self._scroll_area.widget().layout().activate()

        hint = self.sizeHint()
        w = max(self._MIN_WIDTH, min(self._MAX_WIDTH, hint.width()))
        h = max(self._MIN_HEIGHT, min(self._MAX_HEIGHT, hint.height()))
        self.resize(w, h)

        # QScrollArea's size hint ignores word wrap and never goes below its default
        # (a short text left an empty half of the popup): size to the wrapped text
        # exactly, growing and shrinking. Measured from the layout, not the viewport,
        # whose geometry is stale before the first show.
        content = self._scroll_area.widget() if self._scroll_area is not None else None
        if content is not None:
            card_layout = self._card.layout()
            margins = card_layout.contentsMargins()
            inner = w - margins.left() - margins.right()
            if self._fit_widgets:
                # A region's history: fit the newest block, the older ones scroll below it.
                needed = self._newest_block_height(inner)
            elif content.hasHeightForWidth():
                needed = content.heightForWidth(inner)
            else:
                needed = content.sizeHint().height()
            # Header row + gaps, from the layout itself: the window's size hint is capped
            # by the card's maximum height, which made this depend on the history length.
            header = self._header_delta() if not self._header.isHidden() else 0
            chrome = margins.top() + margins.bottom() + header
            self.resize(w, max(self._MIN_HEIGHT, min(self._MAX_HEIGHT, chrome + needed)))

    def _newest_block_height(self, width: int) -> int:
        """Height of the content down to the end of the newest block (and its notice)."""
        spacing = self._scroll_area.widget().layout().spacing()
        heights = [
            w.heightForWidth(width) if w.hasHeightForWidth() else w.sizeHint().height() for w in self._fit_widgets
        ]
        return sum(heights) + spacing * (len(heights) - 1)

    # ── Edge detection & Mouse Resizing / Dragging ────────

    def _detect_resize_edge(self, pos: QPoint) -> str | None:
        r = self.rect()
        m = self._RESIZE_MARGIN
        x, y, w, h = pos.x(), pos.y(), r.width(), r.height()

        # No top edge: it is the header, so grabbing it always moves the window.
        on_right = x >= w - m
        on_bottom = y >= h - m
        on_left = x <= m

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

    def _compact_header_shown(self) -> bool:
        """Compact mode, and the header is on screen only because the popup is engaged."""
        return (
            overlay_behavior.compact()
            and not self._is_loading
            and self._header is not None
            and not self._header.isHidden()
        )

    def _finish_resize(self) -> None:
        """Persist the size once a resize drag ends (not on every mouse move)."""
        if not self._resized:
            return
        self._resized = False
        # Saved as the size at rest: without the header a compact popup shows only now.
        extra = self._header_delta() if self._compact_header_shown() else 0
        try:
            config.POPUP_SIZE = [self.width(), max(self._MIN_HEIGHT, self.height() - extra)]
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

        if self._is_error:
            border = theme.qcolor("error")
        elif self._is_loading or not (self._engaged or self._fresh):
            border = theme.qcolor("dim")  # at rest the frame does not shout
        else:
            border = theme.qcolor("accent")
        painter.setPen(QPen(border, 1))
        painter.drawRect(r)
        painter.end()

    # ── Positioning ──────────────────────────────────────

    def _position_near_anchor(self) -> None:
        self._fit_and_adjust_size()
        self.move(self._place(self.size(), self._anchor, self._screen_rect(), self._app_window_rects(), self._MARGIN))

    def _step_aside_if_covering(self) -> None:
        """After the popup grew in place, move it off an app window it now covers.

        A popup the user dragged stays where they put it.
        """
        if self._moved_by_user:
            return
        avoid = self._app_window_rects()
        if any(self.frameGeometry().intersects(r) for r in avoid):
            self.move(self._place(self.size(), self._anchor, self._screen_rect(), avoid, self._MARGIN))

    def _screen_rect(self) -> QRect:
        if self._anchor is None:
            screen = self._screen_at(QCursor.pos())
        else:
            screen = self._screen_at(self._anchor.center())
        return screen.availableGeometry()

    def _app_window_rects(self) -> list:
        """Visible windows and dialogs of the app (the main window first of all)."""
        return [
            w.frameGeometry()
            for w in QApplication.topLevelWidgets()
            if w is not self and w.isVisible() and not w.isMinimized() and w.windowType() in (Qt.Window, Qt.Dialog)
        ]

    @staticmethod
    def _place(size: QSize, anchor: QRect | None, screen: QRect, avoid: list, margin: int) -> QPoint:
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
            return QPoint(max(screen.x() + margin, min(x, max_x)), max(screen.y() + margin, min(y, max_y)))

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
    position: QPoint | None = None,
    blocks: list[tuple[str, str]] | None = None,
) -> ResultPopup | None:
    """Display translation result or error via popup or Windows toast according
    to config.NOTIFICATION_TYPE. An open popup is updated in place. ``position``: a new
    popup opens there (where the user dragged the last popup of this region).
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
            existing_popup.update_content(source_text, translated_text, is_error=is_error, notice=notice, blocks=blocks)
            return existing_popup
        else:
            popup = ResultPopup(source_text, translated_text, anchor, is_error=is_error, notice=notice, blocks=blocks)
            if position is not None:
                popup.place_at(position)
            popup.show()
            return popup
