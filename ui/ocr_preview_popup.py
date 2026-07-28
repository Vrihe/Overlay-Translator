"""
ui/ocr_preview_popup.py — Floating popup to preview and edit OCR text before translation.
"""

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QFrame, QApplication, QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt5.QtGui import QColor, QPainter, QPainterPath


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

        self._card = QWidget(self)
        self._card.setStyleSheet(
            "QWidget { background-color: #1e1e2c; border-radius: 10px; border: 1px solid #3a3a54; }"
        )
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # Header bar
        header_row = QHBoxLayout()
        lbl_title = QLabel("✏️ Редактирование OCR-текста")
        lbl_title.setStyleSheet("color: #7ca5f5; font-weight: 600; font-size: 10pt; font-family: 'Segoe UI'; border: none;")
        header_row.addWidget(lbl_title)
        header_row.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(20, 20)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; font-weight: bold; font-size: 10pt; }"
            "QPushButton:hover { color: #ff6b6b; }"
        )
        btn_close.clicked.connect(self._on_cancel)
        header_row.addWidget(btn_close)
        card_layout.addLayout(header_row)

        # Text editor
        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(self._raw_text)
        self._text_edit.setStyleSheet(
            "QTextEdit {"
            "  background-color: #151522; color: #e8e8e8; border: 1px solid #2e2e42;"
            "  border-radius: 6px; padding: 8px; font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QTextEdit:focus { border-color: #5b8def; }"
        )
        self._text_edit.setMinimumHeight(90)
        self._text_edit.setMaximumHeight(220)
        card_layout.addWidget(self._text_edit)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton("Отмена")
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #aaa; border: 1px solid #444;"
            "  border-radius: 6px; padding: 5px 14px; font-family: 'Segoe UI'; font-size: 9.5pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._btn_cancel)

        self._btn_translate = QPushButton("Перевести ↵")
        self._btn_translate.setCursor(Qt.PointingHandCursor)
        self._btn_translate.setStyleSheet(
            "QPushButton {"
            "  background: #3b66c4; color: #fff; border: none;"
            "  border-radius: 6px; padding: 5px 18px; font-family: 'Segoe UI'; font-size: 9.5pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a77db; }"
        )
        self._btn_translate.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._btn_translate)

        card_layout.addLayout(btn_row)
        root.addWidget(self._card)

        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 100))
        self._card.setGraphicsEffect(shadow)

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
