"""
ui/ocr_preview_popup.py — Floating popup to preview and edit OCR text before translation.
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QCursor

from i18n import tr
from ui import icons, theme


class OcrPreviewPopup(QWidget):
    """Floating dialog to view and edit OCR-recognized text prior to sending to LLM."""

    # Emitted when user clicks "Translate" or presses Ctrl+Enter. Emits edited text.
    confirmed = pyqtSignal(str)
    cancelled = pyqtSignal()

    _MIN_WIDTH = 340
    _MAX_WIDTH = 650

    def __init__(self, raw_text: str, anchor: QRect | None = None, parent=None):
        super().__init__(parent)
        self._raw_text = raw_text
        self._anchor = anchor

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._build_ui()
        self._position_near_anchor()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        p = theme.current()
        self._card = QWidget(self)
        self._card.setObjectName("ocrCard")
        self._card.setStyleSheet(theme.panel_css("ocrCard", background=p.bg, border=p.accent))
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # Header bar
        header_row = QHBoxLayout()
        lbl_title = QLabel(tr("Редактирование OCR-текста").upper())
        lbl_title.setFont(theme.display_font(9.5, spacing=114))
        lbl_title.setStyleSheet(f"color: {p.accent}; background: transparent;")
        header_row.addWidget(lbl_title)
        header_row.addStretch()

        btn_close = QPushButton()
        btn_close.setFixedSize(24, 24)
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setIcon(icons.icon("close", p.muted, 14, active_color=p.error))
        btn_close.setToolTip(tr("Отмена"))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(theme.btn_icon(danger=True))
        btn_close.clicked.connect(self._on_cancel)
        header_row.addWidget(btn_close)
        card_layout.addLayout(header_row)

        # Text editor
        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(self._raw_text)
        self._text_edit.setStyleSheet(theme.input_css(10, "8px"))
        self._text_edit.setMinimumHeight(90)
        self._text_edit.setMaximumHeight(220)
        card_layout.addWidget(self._text_edit)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton(tr("Отмена"))
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(theme.btn_secondary("5px 14px", 9))
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._btn_cancel)

        self._btn_translate = QPushButton(tr("Перевести ↵").upper())
        self._btn_translate.setCursor(Qt.PointingHandCursor)
        self._btn_translate.setFont(theme.display_font(9.5, spacing=110))
        self._btn_translate.setStyleSheet(theme.btn_primary("5px 18px", 9.5))
        self._btn_translate.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._btn_translate)

        card_layout.addLayout(btn_row)
        root.addWidget(self._card)

        self.setFixedWidth(self._MIN_WIDTH)

    def _position_near_anchor(self) -> None:
        if not self._anchor:
            cursor_pos = QCursor.pos()
            self.move(cursor_pos.x() + 10, cursor_pos.y() + 10)
            return

        screen = QApplication.primaryScreen().geometry()
        x = self._anchor.x()
        y = self._anchor.y() + self._anchor.height() + 10
        if y + 200 > screen.height():
            y = self._anchor.y() - 210

        x = max(10, min(screen.width() - self._MIN_WIDTH - 10, x))
        y = max(10, min(screen.height() - 220 - 10, y))
        self.move(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (event.modifiers() & Qt.ControlModifier):
            self._on_confirm()
        elif event.key() == Qt.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)

    def _on_confirm(self) -> None:
        edited = self._text_edit.toPlainText().strip()
        self.confirmed.emit(edited)
        self.close()

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()
