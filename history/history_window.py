"""
history/history_window.py — Translation history viewer widget.

Features:
  • Displays all cached translation entries from SQLite (cache/store.py) in a QTableWidget.
  • Columns: Date/Time, Language, Original text (truncated to 50 chars with '...'), Translation.
  • Live search filter line edit for filtering original text or translation.
  • Context filter chips ("Все" + every domain present in the records).
  • "Clear history" button with QMessageBox confirmation.
  • HistoryWidget(QWidget): Reusable history viewer widget for dialogs or tabs.
"""

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import cache.store as store
import config
from i18n import tr
from ui import icons, theme
from ui.hud_widgets import page_title


class HistoryWidget(QWidget):
    """Reusable translation history viewer widget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_records: list[dict] = []
        self._domain_filter: str | None = None  # None = all contexts

        self._build_ui()
        self.reload()
        self._connect_signals()

    # ── Shared styles ────────────────────────────────────

    @staticmethod
    def _css(extra: str = "") -> str:
        return f"font-family: '{theme.body_family()}'; background: transparent; {extra}"

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self) -> None:
        p = theme.current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Header row: title + export / clear ──
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        header_layout.addWidget(page_title(tr("История")))
        header_layout.addStretch()

        # C3: Export button
        self._btn_export = QPushButton(tr("Экспорт .txt"))
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setStyleSheet(theme.btn_secondary("7px 14px", 9))
        self._btn_export.clicked.connect(self._on_export_history)
        header_layout.addWidget(self._btn_export)

        self._btn_clear = QPushButton(tr("Очистить"))
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_clear.setStyleSheet(theme.btn_danger("7px 14px", 9))
        header_layout.addWidget(self._btn_clear)
        layout.addLayout(header_layout)

        # ── Toolbar: search + context filter chips ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(tr("Поиск по оригиналу или переводу..."))
        self._search_input.addAction(icons.icon("search", p.muted, 14), QLineEdit.LeadingPosition)
        self._search_input.setMinimumWidth(200)
        self._search_input.setMaximumWidth(320)
        self._search_input.setStyleSheet(theme.input_css(9.5, "6px 8px"))
        toolbar.addWidget(self._search_input, 1)
        toolbar.addSpacing(6)

        self._chips_layout = QHBoxLayout()
        self._chips_layout.setSpacing(6)
        toolbar.addLayout(self._chips_layout)
        toolbar.addStretch()
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chip_group.buttonClicked.connect(self._on_chip_clicked)
        layout.addLayout(toolbar)

        # ── Table Widget ──
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            [tr("Дата / Время").upper(), tr("Язык").upper(), tr("Оригинал").upper(), tr("Перевод").upper()]
        )
        self._table.setStyleSheet(theme.table_css())
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setFocusPolicy(Qt.StrongFocus)

        # Column resize policies
        h_header = self._table.horizontalHeader()
        h_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h_header.setHighlightSections(False)
        h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        h_header.setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(2, 220)

        # ── Footer strip under the table: count + "stored locally" ──
        table_box = QVBoxLayout()
        table_box.setSpacing(0)
        table_box.addWidget(self._table, 1)
        footer = QFrame()
        footer.setObjectName("historyFooter")
        footer.setStyleSheet(
            f"#historyFooter {{ background: {p.rail}; border: 1px solid {p.line}; border-top: none; }}"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 7, 12, 7)

        self._count_label = QLabel(tr("Показано записей: {count}", count=0))
        self._count_label.setFont(theme.body_font(8, medium=True, spacing=110))
        self._count_label.setStyleSheet(f"color: {p.muted}; background: transparent;")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()

        local_lbl = QLabel(tr("Хранится локально").upper())
        local_lbl.setFont(theme.body_font(8, medium=True, spacing=110))
        local_lbl.setStyleSheet(f"color: {p.muted}; background: transparent;")
        footer_layout.addWidget(local_lbl)
        table_box.addWidget(footer)

        layout.addLayout(table_box, 1)

    # ── Context filter chips ─────────────────────────────

    def _chip_css(self) -> str:
        p = theme.current()
        return (
            "QPushButton {"
            f"  background: transparent; color: {p.text_soft}; border: 1px solid {p.line};"
            "  border-radius: 0; padding: 5px 10px;"
            f"  font-family: '{theme.body_family()}'; font-size: 8.5pt;"
            "}"
            f"QPushButton:hover {{ color: {p.text}; border-color: {p.dim}; }}"
            f"QPushButton:focus {{ border-color: {p.accent}; }}"
            f"QPushButton:checked {{ color: {p.accent}; border-color: {p.dim}; background: {p.tint}; }}"
        )

    def _rebuild_chips(self) -> None:
        """One chip per context present in the history, plus "all"."""
        for btn in self._chip_group.buttons():
            self._chip_group.removeButton(btn)
            btn.hide()
            btn.deleteLater()

        present = []
        for rec in self._all_records:
            dom = self._context_of(rec)
            if dom not in present:
                present.append(dom)
        if len(present) < 2:
            self._domain_filter = None
            return  # a single context: nothing to filter
        if self._domain_filter not in present:
            self._domain_filter = None

        try:
            from translate.domain_manager import list_available_domains

            names = {d["id"]: d["display_name"] for d in list_available_domains()}
        except Exception:
            names = {}

        css = self._chip_css()
        for dom in [None] + present:
            label = tr("Все") if dom is None else names.get(dom, dom)
            btn = QPushButton(label.upper())
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(css)
            btn.setProperty("domain", dom)
            btn.setChecked(dom == self._domain_filter)
            self._chip_group.addButton(btn)
            self._chips_layout.addWidget(btn)

    @staticmethod
    def _context_of(rec: dict) -> str:
        """Context profile of a record; NMT entries are cached as "<domain>|<backend>"."""
        return (rec.get("domain_id") or "general").split("|", 1)[0] or "general"

    def _on_chip_clicked(self, btn) -> None:
        self._domain_filter = btn.property("domain")
        self._apply_filters()

    # ── Load Data ────────────────────────────────────────

    def reload(self) -> None:
        """Fetch records from store and populate the table."""
        self._all_records = store.get_all_history()
        self._rebuild_chips()
        self._apply_filters()

    def _populate_table(self, records: list[dict]) -> None:
        self._table.setRowCount(0)
        self._table.setRowCount(len(records))

        for row_idx, rec in enumerate(records):
            # 1. DateTime
            ts = rec.get("timestamp", 0)
            dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
            item_dt = QTableWidgetItem(dt_str)
            item_dt.setForeground(theme.qcolor("muted"))

            # 2. Language
            src = rec.get("source_lang", config.SOURCE_LANG).upper()
            tgt = rec.get("target_lang", config.TARGET_LANG).upper()
            item_lang = QTableWidgetItem(f"{src} → {tgt}")
            item_lang.setForeground(theme.qcolor("accent"))

            # 3. Original text (truncated to 50 chars with ...)
            orig_full = rec.get("source_text", "")
            orig_short = orig_full[:50] + ("..." if len(orig_full) > 50 else "")
            item_orig = QTableWidgetItem(orig_short)
            item_orig.setToolTip(orig_full)
            item_orig.setForeground(theme.qcolor("text_soft"))

            # 4. Translated text
            trans_full = rec.get("translated_text", "")
            item_trans = QTableWidgetItem(trans_full)
            item_trans.setToolTip(trans_full)

            self._table.setItem(row_idx, 0, item_dt)
            self._table.setItem(row_idx, 1, item_lang)
            self._table.setItem(row_idx, 2, item_orig)
            self._table.setItem(row_idx, 3, item_trans)

        self._displayed_records = records
        self._count_label.setText(tr("Показано записей: {count}", count=len(records)).upper())
        self._btn_clear.setEnabled(len(self._all_records) > 0)
        self._btn_export.setEnabled(len(records) > 0)

    # ── Signals ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._search_input.textChanged.connect(self._on_search_changed)
        self._btn_clear.clicked.connect(self._on_clear_clicked)

    # ── Export history (C3) ──────────────────────────────

    def _on_export_history(self) -> None:
        """C3: Export currently filtered history entries to a formatted text file."""
        records = getattr(self, "_displayed_records", [])
        if not records:
            QMessageBox.information(self, tr("Экспорт"), tr("Нет записей для экспорта."))
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Сохранить историю переводов"),
            "history_export.txt",
            tr("Текстовые файлы (*.txt);;Все файлы (*)"),
        )
        if not file_path:
            return

        try:
            lines = []
            for rec in records:
                ts = rec.get("timestamp", 0)
                dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
                src = rec.get("source_lang", config.SOURCE_LANG).upper()
                tgt = rec.get("target_lang", config.TARGET_LANG).upper()
                orig = rec.get("source_text", "")
                trans = rec.get("translated_text", "")

                lines.append(f"[{dt_str}] {src} → {tgt}")
                lines.append(tr("Оригинал:   {text}", text=orig))
                lines.append(tr("Перевод:    {text}", text=trans))
                lines.append("-" * 50)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            QMessageBox.information(
                self,
                tr("Экспорт завершён"),
                tr(
                    "Успешно экспортировано записей: {count}\nФайл: {path}",
                    count=len(records),
                    path=file_path,
                ),
            )
        except Exception as e:
            QMessageBox.critical(self, tr("Ошибка экспорта"), tr("Не удалось сохранить файл:\n{error}", error=e))

    # ── Filter search ────────────────────────────────────

    def _on_search_changed(self, _text: str = "") -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Search text and context chip combined."""
        query = self._search_input.text().strip().lower()
        filtered = self._all_records
        if self._domain_filter is not None:
            filtered = [r for r in filtered if self._context_of(r) == self._domain_filter]
        if query:
            filtered = [
                r
                for r in filtered
                if query in r.get("source_text", "").lower() or query in r.get("translated_text", "").lower()
            ]
        self._populate_table(filtered)

    # ── Clear history ────────────────────────────────────

    def _on_clear_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("Подтверждение очистки"),
            tr("Вы уверены, что хотите удалить всю историю переводов?\nЭто действие нельзя отменить."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            store.clear_history()
            self._search_input.clear()
            self.reload()
