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

from i18n import tr
from ui import theme

from settings.region_presets import (
    load_presets, save_preset, delete_preset, rename_preset,
    update_preset_hotkey, validate_hotkey,
)

logger = logging.getLogger("translator")


def _dialog_css() -> str:
    return f"QDialog {{ background: {theme.current().panel}; }}"


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
        self.setWindowTitle(tr("Назначить бинд — «{name}»", name=preset_name))
        self.resize(380, 200)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet(_dialog_css())
        self.preset_id = preset_id
        self.result_hotkey: str | None = current_hotkey

        self._build_ui(current_hotkey)

    def _build_ui(self, current_hotkey: str | None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        p = theme.current()
        lbl = QLabel(tr("Нажмите комбинацию клавиш для этого пресета:"))
        lbl.setStyleSheet(theme.text_css(p.text, 10))
        layout.addWidget(lbl)

        hint = QLabel(tr("Например: Ctrl+Alt+1, F8, Alt+Shift+T. Бинд будет работать глобально."))
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.label_css("caption"))
        layout.addWidget(hint)

        initial_seq = QKeySequence(current_hotkey.upper()) if current_hotkey else QKeySequence()
        self._key_edit = QKeySequenceEdit(initial_seq)
        self._key_edit.setStyleSheet(
            theme.input_css(11, "8px") + f"QKeySequenceEdit {{ border-color: {p.dim}; color: {p.accent}; }}"
        )
        layout.addWidget(self._key_edit)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_ok = QPushButton(tr("Применить").upper())
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setFont(theme.display_font(9.5, spacing=110))
        btn_ok.setStyleSheet(theme.btn_primary("8px 16px", 9.5))
        btn_ok.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_ok)

        btn_clear = QPushButton(tr("Очистить бинд"))
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(theme.btn_danger("8px 14px", 9))
        btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(btn_clear)

        btn_cancel = QPushButton(tr("Отмена"))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(theme.btn_secondary("8px 14px", 9))
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
            QMessageBox.warning(self, tr("Ошибка бинда"), str(exc))

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
        self.setWindowTitle(tr("Translator Overlay — Пресеты регионов"))
        self.resize(540, 460)
        self.setMinimumSize(440, 360)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet(_dialog_css())

        self._build_ui()
        self._reload_list()

    # ── UI construction ──────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        p = theme.current()

        # Title & Hint
        lbl_title = QLabel(f"<span style='color:{p.accent};'>//</span> " + tr("Пресеты областей экрана").upper())
        lbl_title.setTextFormat(Qt.RichText)
        lbl_title.setFont(theme.display_font(13, spacing=106))
        lbl_title.setStyleSheet(f"color: {p.text}; background: transparent;")
        layout.addWidget(lbl_title)

        lbl_hint = QLabel(tr(
            "Сохранённые области экрана. Назначьте бинд для быстрого разового перевода "
            "или запустите опциональный автомониторинг."
        ))
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(theme.label_css("muted"))
        layout.addWidget(lbl_hint)

        # Preset list
        self._list = QListWidget()
        self._list.setStyleSheet(theme.list_css())
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.doubleClicked.connect(self._on_translate_now)
        layout.addWidget(self._list, 1)

        # Button row 1: Preset management & hotkeys
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_new = self._make_button(tr("+ Новый"), theme.btn_accent("6px 12px", 9))
        self._btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(self._btn_new)

        self._btn_hotkey = self._make_button(tr("Назначить бинд"), theme.btn_secondary("6px 12px", 9))
        self._btn_hotkey.clicked.connect(self._on_set_hotkey)
        btn_row.addWidget(self._btn_hotkey)

        self._btn_clear_hotkey = self._make_button(tr("Сбросить"), theme.btn_secondary("6px 12px", 9))
        self._btn_clear_hotkey.clicked.connect(self._on_clear_hotkey)
        btn_row.addWidget(self._btn_clear_hotkey)

        self._btn_rename = self._make_button(tr("Имя"), theme.btn_secondary("6px 12px", 9))
        self._btn_rename.clicked.connect(self._on_rename)
        btn_row.addWidget(self._btn_rename)

        self._btn_delete = self._make_button(tr("Удалить"), theme.btn_danger("6px 12px", 9))
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        layout.addLayout(btn_row)

        # Action row: Primary translation & optional auto-monitoring
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._btn_translate = QPushButton(tr("Перевести область").upper())
        self._btn_translate.setCursor(Qt.PointingHandCursor)
        self._btn_translate.setFont(theme.display_font(10, spacing=110))
        self._btn_translate.setStyleSheet(theme.btn_primary("9px 18px", 10))
        self._btn_translate.clicked.connect(self._on_translate_now)
        action_row.addWidget(self._btn_translate)

        self._btn_monitor = QPushButton(tr("Автомониторинг (10 сек)"))
        self._btn_monitor.setCursor(Qt.PointingHandCursor)
        self._btn_monitor.setStyleSheet(theme.btn_accent("9px 14px", 9))
        self._btn_monitor.clicked.connect(self._on_start_monitoring)
        action_row.addWidget(self._btn_monitor)

        action_row.addStretch()

        self._btn_cancel = QPushButton(tr("Закрыть"))
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(theme.btn_secondary("9px 18px", 9.5))
        self._btn_cancel.clicked.connect(self.reject)
        action_row.addWidget(self._btn_cancel)

        layout.addLayout(action_row)

    @staticmethod
    def _make_button(text: str, css: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(css)
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
            hk_badge = f"[{hk.upper()}]" if hk else tr("[Нет бинда]")
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
            tr("Имя пресета"),
            tr("Введите имя для нового пресета региона:"),
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
            QMessageBox.warning(self, tr("Ошибка сохранения"), str(e))

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
                QMessageBox.warning(self, tr("Ошибка бинда"), str(e))

    def _on_clear_hotkey(self) -> None:
        preset = self._selected_preset()
        if preset is None or not preset.get("hotkey"):
            return
        try:
            update_preset_hotkey(preset["id"], None)
            self._reload_list()
            self.presets_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, tr("Ошибка сброса бинда"), str(e))

    def _on_rename(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        new_name, ok = QInputDialog.getText(
            self,
            tr("Переименовать пресет"),
            tr("Новое имя:"),
            text=preset.get("name", ""),
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_preset(preset["id"], new_name)
            self._reload_list()
            self.presets_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, tr("Ошибка переименования"), str(e))

    def _on_delete(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        reply = QMessageBox.question(
            self,
            tr("Удаление пресета"),
            tr("Удалить пресет «{name}»?", name=preset.get("name", "???")),
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
            QMessageBox.warning(self, tr("Ошибка удаления"), str(e))

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
