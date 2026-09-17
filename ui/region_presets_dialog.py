"""
ui/region_presets_dialog.py — dialog for managing named Live Monitor region presets.

Provides a QDialog listing saved region presets with controls to:
- Assign / clear custom global hotkeys (binds) for each preset.
- Execute single-shot translation on demand (primary action).
- Optionally launch 10-second background auto-monitoring (secondary action).
- Create, rename, and delete presets.
"""

import logging
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem,
    QInputDialog, QMessageBox, QWidget, QKeySequenceEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence

from settings.region_presets import (
    load_presets, save_preset, delete_preset, rename_preset,
    update_preset_hotkey, validate_hotkey,
)

logger = logging.getLogger("translator")

# ── Shared style constants (matching ui/settings_dialog.py) ──

_DIALOG_BG = "#1c1c24"
_CARD_BG = "#232334"
_INPUT_BG = "#2a2a3e"
_ACCENT = "#5b8def"
_ACCENT_HOVER = "#4a7de0"
_TEXT = "#e0e0e0"
_TEXT_DIM = "#999"
_BORDER = "#444"
_BORDER_LIGHT = "#3a3a4e"
_FONT = "Segoe UI"
_DANGER = "#ff6b6b"
_DANGER_BG_HOVER = "rgba(255, 107, 107, 0.15)"
_SUCCESS = "#2d8c5a"
_SUCCESS_HOVER = "#34a068"


class HotkeyInputDialog(QDialog):
    """Modal dialog for capturing and validating a keyboard shortcut."""

    def __init__(
        self,
        current_hotkey: str | None = None,
        preset_id: str | None = None,
        preset_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Назначить бинд — «{preset_name}»")
        self.resize(380, 200)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet(f"QDialog {{ background: {_DIALOG_BG}; }}")
        self.preset_id = preset_id
        self.result_hotkey: str | None = current_hotkey

        self._build_ui(current_hotkey)

    def _build_ui(self, current_hotkey: str | None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Нажмите комбинацию клавиш для этого пресета:")
        lbl.setStyleSheet(f"color: {_TEXT}; font-family: '{_FONT}'; font-size: 10pt; font-weight: 600;")
        layout.addWidget(lbl)

        hint = QLabel("Например: Ctrl+Alt+1, F8, Alt+Shift+T. Бинд будет работать глобально.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_TEXT_DIM}; font-family: '{_FONT}'; font-size: 8.5pt;")
        layout.addWidget(hint)

        initial_seq = QKeySequence(current_hotkey.upper()) if current_hotkey else QKeySequence()
        self._key_edit = QKeySequenceEdit(initial_seq)
        self._key_edit.setStyleSheet(
            f"QKeySequenceEdit {{"
            f"  background: {_INPUT_BG}; color: #fff; border: 1px solid {_ACCENT};"
            f"  border-radius: 6px; padding: 8px; font-family: '{_FONT}'; font-size: 11pt;"
            f"}}"
        )
        layout.addWidget(self._key_edit)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_ok = QPushButton("✔ Применить")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_ACCENT}; color: #fff; border: none; border-radius: 6px;"
            f"  padding: 8px 16px; font-family: '{_FONT}'; font-size: 9.5pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {_ACCENT_HOVER}; }}"
        )
        btn_ok.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_ok)

        btn_clear = QPushButton("❌ Очистить бинд")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_INPUT_BG}; color: {_DANGER}; border: 1px solid {_BORDER};"
            f"  border-radius: 6px; padding: 8px 14px; font-family: '{_FONT}'; font-size: 9.5pt;"
            f"}}"
            f"QPushButton:hover {{ background: {_DANGER_BG_HOVER}; }}"
        )
        btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(btn_clear)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: #aaa; border: 1px solid {_BORDER};"
            f"  border-radius: 6px; padding: 8px 14px; font-family: '{_FONT}'; font-size: 9.5pt;"
            f"}}"
            f"QPushButton:hover {{ background: {_INPUT_BG}; color: #ccc; }}"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)

    def _on_apply(self) -> None:
        seq = self._key_edit.keySequence().toString()
        hk_str = seq.lower().strip() if seq.strip() else None
        try:
            valid_hk = validate_hotkey(hk_str, current_preset_id=self.preset_id)
            self.result_hotkey = valid_hk
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка бинда", str(exc))

    def _on_clear(self) -> None:
        self.result_hotkey = None
        self.accept()


class RegionPresetsDialog(QDialog):
    """Dialog for managing named region presets.

    Signals:
        preset_translate(int, int, int, int): Emitted when user triggers single-shot
            translation for (x1, y1, x2, y2).
        preset_monitor(int, int, int, int): Emitted when user explicitly starts
            periodic auto-monitoring for (x1, y1, x2, y2).
        request_new_preset(): Emitted when user clicks 'New'.
        presets_updated(): Emitted whenever presets list or hotkeys are modified.
    """

    preset_translate = pyqtSignal(int, int, int, int)
    preset_monitor = pyqtSignal(int, int, int, int)
    request_new_preset = pyqtSignal()
    presets_updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Translator Overlay — Пресеты регионов")
        self.resize(540, 460)
        self.setMinimumSize(440, 360)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet(f"QDialog {{ background: {_DIALOG_BG}; }}")

        self._build_ui()
        self._reload_list()

    # ── UI construction ──────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title & Hint
        lbl_title = QLabel("📋 Пресеты областей экрана")
        lbl_title.setStyleSheet(
            f"font-family: '{_FONT}'; font-size: 13pt; font-weight: 600; "
            f"color: {_TEXT}; background: transparent;"
        )
        layout.addWidget(lbl_title)

        lbl_hint = QLabel(
            "Сохранённые области экрана. Назначьте бинд для быстрого разового перевода "
            "или запустите опциональный автомониторинг."
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(
            f"font-family: '{_FONT}'; font-size: 9pt; color: {_TEXT_DIM}; "
            "background: transparent; margin-bottom: 2px;"
        )
        layout.addWidget(lbl_hint)

        # Preset list
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{"
            f"  background: {_CARD_BG}; color: {_TEXT}; border: 1px solid {_BORDER_LIGHT};"
            f"  border-radius: 8px; padding: 4px;"
            f"  font-family: '{_FONT}'; font-size: 10pt;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 8px 10px; border-bottom: 1px solid {_BORDER_LIGHT};"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background: {_INPUT_BG}; color: {_TEXT};"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background: #2a2a42;"
            f"}}"
        )
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.doubleClicked.connect(self._on_translate_now)
        layout.addWidget(self._list, 1)

        # Button row 1: Preset management & hotkeys
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_new = self._make_button("➕ Новый", _ACCENT, "#fff", _ACCENT_HOVER)
        self._btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(self._btn_new)

        self._btn_hotkey = self._make_button("⌨ Назначить бинд", _INPUT_BG, _TEXT, "#3a3a5c")
        self._btn_hotkey.clicked.connect(self._on_set_hotkey)
        btn_row.addWidget(self._btn_hotkey)

        self._btn_clear_hotkey = self._make_button("❌ Сбросить", _INPUT_BG, _TEXT_DIM, "#3a3a5c")
        self._btn_clear_hotkey.clicked.connect(self._on_clear_hotkey)
        btn_row.addWidget(self._btn_clear_hotkey)

        self._btn_rename = self._make_button("✏️ Имя", _INPUT_BG, _TEXT_DIM, "#3a3a5c")
        self._btn_rename.clicked.connect(self._on_rename)
        btn_row.addWidget(self._btn_rename)

        self._btn_delete = self._make_button("🗑️ Удалить", _INPUT_BG, _DANGER, _DANGER_BG_HOVER)
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        layout.addLayout(btn_row)

        # Action row: Primary translation & optional auto-monitoring
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._btn_translate = QPushButton("▶ Перевести область")
        self._btn_translate.setCursor(Qt.PointingHandCursor)
        self._btn_translate.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_SUCCESS}; color: #fff; border: none;"
            f"  border-radius: 6px; padding: 9px 18px;"
            f"  font-family: '{_FONT}'; font-size: 10pt; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background: {_SUCCESS_HOVER}; }}"
            f"QPushButton:disabled {{ background: #1f2f28; color: #555; }}"
        )
        self._btn_translate.clicked.connect(self._on_translate_now)
        action_row.addWidget(self._btn_translate)

        self._btn_monitor = QPushButton("👁 Автомониторинг (10 сек)")
        self._btn_monitor.setCursor(Qt.PointingHandCursor)
        self._btn_monitor.setStyleSheet(
            f"QPushButton {{"
            f"  background: #3a3a56; color: #ccc; border: 1px solid {_BORDER};"
            f"  border-radius: 6px; padding: 9px 14px;"
            f"  font-family: '{_FONT}'; font-size: 9pt;"
            f"}}"
            f"QPushButton:hover {{ background: #4a4a6e; color: #fff; }}"
            f"QPushButton:disabled {{ background: #222230; color: #555; }}"
        )
        self._btn_monitor.clicked.connect(self._on_start_monitoring)
        action_row.addWidget(self._btn_monitor)

        action_row.addStretch()

        self._btn_cancel = QPushButton("Закрыть")
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: #aaa; border: 1px solid {_BORDER};"
            f"  border-radius: 6px; padding: 9px 18px;"
            f"  font-family: '{_FONT}'; font-size: 10pt;"
            f"}}"
            f"QPushButton:hover {{ background: {_INPUT_BG}; color: #ccc; }}"
        )
        self._btn_cancel.clicked.connect(self.reject)
        action_row.addWidget(self._btn_cancel)

        layout.addLayout(action_row)

    @staticmethod
    def _make_button(text: str, bg: str, fg: str, hover_bg: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {fg}; border: 1px solid {_BORDER};"
            f"  border-radius: 6px; padding: 6px 12px;"
            f"  font-family: '{_FONT}'; font-size: 9pt; font-weight: 500;"
            f"}}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            f"QPushButton:disabled {{ background: #1a1a24; color: #444; border-color: #333; }}"
        )
        return btn

    # ── List management ──────────────────────────────────

    def _reload_list(self) -> None:
        """Refresh the QListWidget from persisted presets."""
        self._list.clear()
        presets = load_presets()
        for p in presets:
            name = p.get("name", "???")
            x1, y1 = p.get("x1", 0), p.get("y1", 0)
            x2, y2 = p.get("x2", 0), p.get("y2", 0)
            w, h = x2 - x1, y2 - y1
            hk = p.get("hotkey")
            hk_badge = f"[{hk.upper()}]" if hk else "[Нет бинда]"
            label = f"{hk_badge:<16} {name}    ({x1}, {y1}) → ({x2}, {y2})  [{w}×{h}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, p)
            self._list.addItem(item)

        has_items = self._list.count() > 0
        self._btn_translate.setEnabled(has_items)
        self._btn_monitor.setEnabled(has_items)
        self._btn_hotkey.setEnabled(has_items)
        self._btn_clear_hotkey.setEnabled(has_items)
        self._btn_rename.setEnabled(has_items)
        self._btn_delete.setEnabled(has_items)

        if has_items:
            self._list.setCurrentRow(0)

    def _selected_preset(self) -> dict | None:
        """Return the currently selected preset dict, or None."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    # ── Slots ────────────────────────────────────────────

    def _on_new(self) -> None:
        """Request a new region selection from the caller."""
        self.request_new_preset.emit()

    def add_new_preset(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Called by the main app after region selection to prompt for a name and save."""
        name, ok = QInputDialog.getText(
            self,
            "Имя пресета",
            "Введите имя для нового пресета региона:",
            text="",
        )
        if not ok or not name.strip():
            return
        try:
            save_preset(name, x1, y1, x2, y2)
            self._reload_list()
            self.presets_updated.emit()
            logger.info("Region preset '%s' created from dialog.", name.strip())
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка сохранения", str(e))

    def _on_set_hotkey(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        dlg = HotkeyInputDialog(
            current_hotkey=preset.get("hotkey"),
            preset_id=preset.get("id"),
            preset_name=preset.get("name", "???"),
            parent=self,
        )
        if dlg.exec_() == QDialog.Accepted:
            try:
                update_preset_hotkey(preset["id"], dlg.result_hotkey)
                self._reload_list()
                self.presets_updated.emit()
            except ValueError as e:
                QMessageBox.warning(self, "Ошибка бинда", str(e))

    def _on_clear_hotkey(self) -> None:
        preset = self._selected_preset()
        if preset is None or not preset.get("hotkey"):
            return
        try:
            update_preset_hotkey(preset["id"], None)
            self._reload_list()
            self.presets_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка сброса бинда", str(e))

    def _on_rename(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать пресет",
            "Новое имя:",
            text=preset.get("name", ""),
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_preset(preset["id"], new_name)
            self._reload_list()
            self.presets_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка переименования", str(e))

    def _on_delete(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        reply = QMessageBox.question(
            self,
            "Удаление пресета",
            f"Удалить пресет «{preset.get('name', '???')}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_preset(preset["id"])
            self._reload_list()
            self.presets_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка удаления", str(e))

    def _on_translate_now(self) -> None:
        """Primary action: single-shot translation of the selected preset region."""
        preset = self._selected_preset()
        if preset is None:
            return
        x1, y1 = preset.get("x1", 0), preset.get("y1", 0)
        x2, y2 = preset.get("x2", 0), preset.get("y2", 0)
        logger.info("Executing preset translation '%s' (%d,%d)→(%d,%d)", preset.get("name"), x1, y1, x2, y2)
        self.preset_translate.emit(x1, y1, x2, y2)
        self.accept()

    def _on_start_monitoring(self) -> None:
        """Secondary action: explicitly launch 10s live auto-monitoring."""
        preset = self._selected_preset()
        if preset is None:
            return
        x1, y1 = preset.get("x1", 0), preset.get("y1", 0)
        x2, y2 = preset.get("x2", 0), preset.get("y2", 0)
        logger.info("Starting optional live monitoring for preset '%s' (%d,%d)→(%d,%d)", preset.get("name"), x1, y1, x2, y2)
        self.preset_monitor.emit(x1, y1, x2, y2)
        self.accept()
