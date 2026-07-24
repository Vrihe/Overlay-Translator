"""
history/history_window.py — Translation history viewer widget and window.

Features:
  • Displays all cached translation entries from SQLite (cache/store.py) in a QTableWidget.
  • Columns: Date/Time, Language, Original text (truncated to 50 chars with '...'), Translation.
  • Live search filter line edit for filtering original text or translation.
  • "Clear history" button with QMessageBox confirmation.
  • HistoryWidget(QWidget): Reusable history viewer widget for dialogs or tabs.
  • HistoryWindow(QDialog): Standalone non-modal history dialog wrapper.
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QWidget, QApplication,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPainterPath, QColor

import config
import cache.store as store


class HistoryWidget(QWidget):
    """Reusable translation history viewer widget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_records: list[dict] = []

        self._build_ui()
        self.reload()
        self._connect_signals()

    # ── Shared styles ────────────────────────────────────

    @staticmethod
    def _css(extra: str = "") -> str:
        return f"font-family: 'Segoe UI'; background: transparent; {extra}"

    _INPUT_CSS = (
        "QLineEdit {"
        "  background: #2a2a3e; color: #e0e0e0; border: 1px solid #444;"
        "  border-radius: 6px; padding: 6px 12px;"
        "  font-family: 'Segoe UI'; font-size: 10pt;"
        "}"
        "QLineEdit:focus {"
        "  border-color: #5b8def;"
        "}"
    )

    _TABLE_CSS = (
        "QTableWidget {"
        "  background-color: #1c1c2a; color: #e0e0e0; gridline-color: #2a2a3e;"
        "  border: 1px solid #3a3a4e; border-radius: 8px;"
        "  font-family: 'Segoe UI'; font-size: 9.5pt;"
        "  outline: none;"
        "}"
        "QTableWidget::item {"
        "  background-color: #1c1c2a; color: #e0e0e0; padding: 6px 8px;"
        "}"
        "QTableWidget::item:alternate {"
        "  background-color: #25253a; color: #e0e0e0;"
        "}"
        "QTableWidget::item:hover {"
        "  background-color: #2e2e46;"
        "}"
        "QTableWidget::item:selected {"
        "  background-color: #3e3e60; color: #ffffff;"
        "}"
        "QHeaderView::section {"
        "  background-color: #151522; color: #aaa; padding: 8px 10px;"
        "  border: none; border-bottom: 1px solid #3a3a4e;"
        "  font-family: 'Segoe UI'; font-size: 9.5pt; font-weight: 600;"
        "}"
        "QTableWidget QTableCornerButton::section {"
        "  background-color: #151522; border: none;"
        "}"
    )

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Header row (Search input) ──
        header_layout = QHBoxLayout()
        header_layout.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Поиск по оригиналу или переводу...")
        self._search_input.setFixedWidth(280)
        self._search_input.setStyleSheet(self._INPUT_CSS)
        header_layout.addWidget(self._search_input)

        layout.addLayout(header_layout)

        # ── Table Widget ──
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Дата / Время", "Язык", "Оригинал", "Перевод"])
        self._table.setStyleSheet(self._TABLE_CSS)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Column resize policies
        h_header = self._table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(2, 220)

        layout.addWidget(self._table, 1)

        # ── Bottom row (Count + Clear button) ──
        bottom_layout = QHBoxLayout()

        self._count_label = QLabel("Всего записей: 0")
        self._count_label.setStyleSheet(self._css("color: #888899; font-size: 9.5pt;"))
        bottom_layout.addWidget(self._count_label)

        bottom_layout.addStretch()

        self._btn_clear = QPushButton("🗑 Очистить историю")
        self._btn_clear.setStyleSheet(
            "QPushButton {"
            "  background: #3a2228; color: #ff6b6b; border: 1px solid #5a2c35;"
            "  border-radius: 6px; padding: 7px 16px;"
            "  font-family: 'Segoe UI'; font-size: 9.5pt; font-weight: 500;"
            "}"
            "QPushButton:hover { background: #502730; color: #ff8585; }"
            "QPushButton:disabled { background: #2a1a1e; color: #664444; border-color: #3a2025; }"
        )
        bottom_layout.addWidget(self._btn_clear)

        layout.addLayout(bottom_layout)

    # ── Load Data ────────────────────────────────────────

    def reload(self) -> None:
        """Fetch records from store and populate the table."""
        self._all_records = store.get_all_history()
        self._populate_table(self._all_records)

    def _populate_table(self, records: list[dict]) -> None:
        self._table.setRowCount(0)
        self._table.setRowCount(len(records))

        lang_pair = f"{config.SOURCE_LANG.upper()} → {config.TARGET_LANG.upper()}"

        for row_idx, rec in enumerate(records):
            # 1. DateTime
            ts = rec.get("timestamp", 0)
            dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
            item_dt = QTableWidgetItem(dt_str)
            item_dt.setTextAlignment(Qt.AlignCenter)

            # 2. Language
            item_lang = QTableWidgetItem(lang_pair)
            item_lang.setTextAlignment(Qt.AlignCenter)

            # 3. Original text (truncated to 50 chars with ...)
            orig_full = rec.get("source_text", "")
            orig_short = orig_full[:50] + ("..." if len(orig_full) > 50 else "")
            item_orig = QTableWidgetItem(orig_short)
            item_orig.setToolTip(orig_full)

            # 4. Translated text
            trans_full = rec.get("translated_text", "")
            item_trans = QTableWidgetItem(trans_full)
            item_trans.setToolTip(trans_full)

            self._table.setItem(row_idx, 0, item_dt)
            self._table.setItem(row_idx, 1, item_lang)
            self._table.setItem(row_idx, 2, item_orig)
            self._table.setItem(row_idx, 3, item_trans)

        self._count_label.setText(f"Всего записей: {len(records)}")
        self._btn_clear.setEnabled(len(records) > 0)

    # ── Signals ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._search_input.textChanged.connect(self._on_search_changed)
        self._btn_clear.clicked.connect(self._on_clear_clicked)

    # ── Filter search ────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        query = text.strip().lower()
        if not query:
            filtered = self._all_records
        else:
            filtered = [
                r for r in self._all_records
                if query in r.get("source_text", "").lower()
                or query in r.get("translated_text", "").lower()
            ]
        self._populate_table(filtered)

    # ── Clear history ────────────────────────────────────

    def _on_clear_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "Подтверждение очистки",
            "Вы уверены, что хотите удалить всю историю переводов?\nЭто действие нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            store.clear_history()
            self._search_input.clear()
            self.reload()


class HistoryWindow(QDialog):
    """Non-modal translation history window with dark theme."""

    _WIDTH = 750
    _HEIGHT = 500

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Translator Overlay — История переводов")
        self.resize(self._WIDTH, self._HEIGHT)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowCloseButtonHint
            | Qt.WindowMinMaxButtonsHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # ── Header row (Title) ──
        header_layout = QHBoxLayout()
        title = QLabel("📜 История переводов")
        title.setStyleSheet(HistoryWidget._css("color: #e8e8e8; font-size: 13pt; font-weight: 600;"))
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # ── History Widget ──
        self.history_widget = HistoryWidget(self._card)
        layout.addWidget(self.history_widget, 1)

        # ── Bottom row (Close button) ──
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        self._btn_close = QPushButton("Закрыть")
        self._btn_close.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #999; border: 1px solid #444;"
            "  border-radius: 6px; padding: 7px 18px;"
            "  font-family: 'Segoe UI'; font-size: 9.5pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )
        self._btn_close.clicked.connect(self.close)
        bottom_layout.addWidget(self._btn_close)

        layout.addLayout(bottom_layout)

        root.addWidget(self._card)

    # ── Background painting ──────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        r = self.rect()
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 12, 12)
        painter.fillPath(path, QColor(28, 28, 36, 245))

        painter.setPen(QColor(255, 255, 255, 15))
        painter.drawPath(path)
        painter.end()
