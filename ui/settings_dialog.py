"""
ui/settings_dialog.py — runtime settings widget and dialog.

Provides:
  • SettingsWidget: reusable QWidget containing all settings controls.
  • SettingsDialog: non-modal QDialog wrapper for SettingsWidget.
  • ProfileEditorDialog: modal QDialog for creating and editing custom domain profiles.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QSpinBox, QWidget, QApplication, QGroupBox, QMessageBox,
    QTextEdit, QScrollArea, QFrame, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMetaObject, Q_ARG
from PyQt5.QtGui import QPainter, QPainterPath, QColor

from typing import Any
import config
import settings
from settings import config_manager
from translate.llm_client import reset_client

_SOURCE_LANGUAGES = [
    ("auto", "Автоопределение"),
    ("en", "English"),
    ("ru", "Русский"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("zh", "中文"),
    ("ar", "العربية"),
    ("tr", "Türkçe"),
    ("pl", "Polski"),
    ("uk", "Українська"),
]

_TARGET_LANGUAGES = [
    ("ru", "Русский"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("zh", "中文"),
    ("ar", "العربية"),
    ("tr", "Türkçe"),
    ("pl", "Polski"),
    ("uk", "Українська"),
]

_ENGINES = [
    ("llm_text",   "OCR → LLM (текстовый)"),
    ("llm_vision", "LLM Vision (картинка)"),
    ("api",        "OCR → Google/DeepL API"),
]

# B1: Preset list of OpenRouter models requested by user.
# (model_id, display_name) — model_id is used as QComboBox itemData.
_OPENROUTER_MODELS: list[tuple[str, str]] = [
    ("openai/gpt-oss-20b:free",      "GPT OSS 20B (free)"),
    ("google/gemma-4-31b-it:free",  "Google Gemma 4 31B (free)"),
    ("poolside/laguna-s-2.1:free",  "Poolside Laguna S 2.1 (free)"),
    ("__custom__",                  "Другая модель..."),
]

# B3: Short hints shown below the model combo for preset models.
_MODEL_HINTS: dict[str, str] = {
    "openai/gpt-oss-20b:free":      "✶ Бесплатно · Базовая открытая модель",
    "google/gemma-4-31b-it:free":  "✶ Бесплатно · Новая мощная открытая модель Google",
    "poolside/laguna-s-2.1:free":  "✶ Бесплатно · Быстрая компактная модель для перевода",
    "__custom__":                  "Впишите точный ID модели с сайта openrouter.ai",
}


class _NllbPreloadWorker(QThread):
    """Load the local NLLB model off the UI thread so the dialog stays responsive."""

    finished_with_status = pyqtSignal(bool, str)  # (ok, message)

    def run(self) -> None:
        from translate.backend import BACKEND_NLLB, preload
        ok, message = preload(BACKEND_NLLB)
        self.finished_with_status.emit(ok, message)


class _ExampleRowWidget(QWidget):
    """Row widget containing source text, translation text, and a remove button."""

    def __init__(self, source: str = "", translation: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.src_input = QLineEdit(source)
        self.src_input.setPlaceholderText("Оригинал (напр. HP)")
        self.src_input.setStyleSheet(
            "QLineEdit {"
            "  background: #1e1e2d; color: #e0e0e0; border: 1px solid #444;"
            "  border-radius: 4px; padding: 5px 8px; font-size: 9.5pt;"
            "}"
        )

        lbl_arrow = QLabel("→")
        lbl_arrow.setStyleSheet("color: #888; font-size: 10pt; background: transparent;")

        self.trans_input = QLineEdit(translation)
        self.trans_input.setPlaceholderText("Перевод (напр. ОЗ)")
        self.trans_input.setStyleSheet(
            "QLineEdit {"
            "  background: #1e1e2d; color: #e0e0e0; border: 1px solid #444;"
            "  border-radius: 4px; padding: 5px 8px; font-size: 9.5pt;"
            "}"
        )

        self.btn_delete = QPushButton("✕")
        self.btn_delete.setFixedSize(24, 24)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #ff6b6b; border: none; font-weight: bold;"
            "}"
            "QPushButton:hover { background: rgba(255, 107, 107, 0.15); border-radius: 4px; }"
        )
        self.btn_delete.clicked.connect(self.deleteLater)

        layout.addWidget(self.src_input, 1)
        layout.addWidget(lbl_arrow)
        layout.addWidget(self.trans_input, 1)
        layout.addWidget(self.btn_delete)

    def get_data(self) -> dict[str, str] | None:
        s = self.src_input.text().strip()
        t = self.trans_input.text().strip()
        if s and t:
            return {"source": s, "translation": t}
        return None


class ProfileEditorDialog(QDialog):
    """Dialog for creating or editing a custom domain profile."""

    def __init__(self, parent=None, profile_data: dict[str, Any] | None = None):
        super().__init__(parent)
        self._profile_data = profile_data or {}
        self._existing_id = self._profile_data.get("id")

        title_str = "Редактирование профиля" if self._existing_id else "Создание профиля контекста"
        self.setWindowTitle(f"Translator Overlay — {title_str}")
        self.resize(520, 520)
        self.setMinimumSize(420, 420)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet("QDialog { background: #1c1c24; }")

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title
        title_text = "✏️ Редактирование профиля" if self._existing_id else "✨ Новый профиль контекста"
        lbl_title = QLabel(title_text)
        lbl_title.setStyleSheet("font-family: 'Segoe UI'; font-size: 13pt; font-weight: 600; color: #e8e8e8;")
        layout.addWidget(lbl_title)

        # Display name
        lbl_name = QLabel("Название профиля (display_name):")
        lbl_name.setStyleSheet("font-family: 'Segoe UI'; color: #ccc; font-size: 9.5pt;")
        layout.addWidget(lbl_name)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Например: Фэнтези РПГ, Медицина, Юриспруденция...")
        self._name_input.setStyleSheet(
            "QLineEdit {"
            "  background: #262636; color: #e0e0e0; border: 1px solid #444;"
            "  border-radius: 6px; padding: 7px 10px; font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QLineEdit:focus { border-color: #5b8def; }"
        )
        layout.addWidget(self._name_input)

        # System prompt
        lbl_prompt = QLabel("Инструкция для ИИ (system_prompt):")
        lbl_prompt.setStyleSheet("font-family: 'Segoe UI'; color: #ccc; font-size: 9.5pt;")
        layout.addWidget(lbl_prompt)

        self._prompt_input = QTextEdit()
        self._prompt_input.setPlaceholderText(
            "Опишите роль ИИ и правила перевода терминов, напр.:\n"
            "Ты опытный переводчик фэнтези игр. Переводи игровые термины (HP -> ОЗ, Mana -> Мана). "
            "Сохраняй геймерский сленг и атмосферу."
        )
        self._prompt_input.setStyleSheet(
            "QTextEdit {"
            "  background: #262636; color: #e0e0e0; border: 1px solid #444;"
            "  border-radius: 6px; padding: 8px 10px; font-family: 'Segoe UI'; font-size: 9.5pt;"
            "}"
            "QTextEdit:focus { border-color: #5b8def; }"
        )
        self._prompt_input.setFixedHeight(120)
        layout.addWidget(self._prompt_input)

        # Few-Shot examples header row
        ex_header = QHBoxLayout()
        lbl_ex = QLabel("Примеры перевода (Few-Shot Examples):")
        lbl_ex.setStyleSheet("font-family: 'Segoe UI'; color: #ccc; font-size: 9.5pt; font-weight: 600;")
        ex_header.addWidget(lbl_ex)
        ex_header.addStretch()

        self._btn_add_ex = QPushButton("➕ Добавить пример")
        self._btn_add_ex.setCursor(Qt.PointingHandCursor)
        self._btn_add_ex.setStyleSheet(
            "QPushButton {"
            "  background: #2a2a3e; color: #5b8def; border: 1px solid #5b8def;"
            "  border-radius: 5px; padding: 4px 10px; font-family: 'Segoe UI'; font-size: 8.5pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #3a3a5c; }"
        )
        self._btn_add_ex.clicked.connect(self._add_example_row)
        ex_header.addWidget(self._btn_add_ex)
        layout.addLayout(ex_header)

        # Scroll area for examples
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._examples_container = QWidget()
        self._examples_layout = QVBoxLayout(self._examples_container)
        self._examples_layout.setContentsMargins(0, 0, 0, 0)
        self._examples_layout.setSpacing(6)
        self._examples_layout.addStretch()

        scroll.setWidget(self._examples_container)
        layout.addWidget(scroll, 1)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_cancel = QPushButton("Отмена")
        self._btn_cancel.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #aaa; border: 1px solid #444;"
            "  border-radius: 6px; padding: 8px 18px; font-family: 'Segoe UI'; font-size: 9.5pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_save = QPushButton("Сохранить профиль")
        self._btn_save.setStyleSheet(
            "QPushButton {"
            "  background: #5b8def; color: #fff; border: none;"
            "  border-radius: 6px; padding: 8px 20px;"
            "  font-family: 'Segoe UI'; font-size: 9.5pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a7de0; }"
        )
        self._btn_save.clicked.connect(self._on_save)

        btn_row.addStretch()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

    def _add_example_row(self, source: str = "", translation: str = ""):
        row = _ExampleRowWidget(source, translation)
        count = self._examples_layout.count()
        self._examples_layout.insertWidget(count - 1, row)

    def _load_data(self):
        if not self._profile_data:
            return
        self._name_input.setText(self._profile_data.get("display_name", ""))
        self._prompt_input.setPlainText(self._profile_data.get("system_prompt", ""))
        examples = self._profile_data.get("few_shot_examples", [])
        for ex in examples:
            if isinstance(ex, dict):
                self._add_example_row(ex.get("source", ""), ex.get("translation", ""))

    def _on_save(self):
        name = self._name_input.text().strip()
        prompt = self._prompt_input.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка ввода", "Введите название профиля.")
            return
        if not prompt:
            QMessageBox.warning(self, "Ошибка ввода", "Заполните системный промпт для ИИ.")
            return

        examples = []
        for i in range(self._examples_layout.count() - 1):
            w = self._examples_layout.itemAt(i).widget()
            if isinstance(w, _ExampleRowWidget):
                data = w.get_data()
                if data:
                    examples.append(data)

        try:
            from translate.domain_manager import save_custom_profile
            save_custom_profile(
                display_name=name,
                system_prompt=prompt,
                few_shot_examples=examples,
                existing_id=self._existing_id,
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить профиль:\n{e}")


class SettingsWidget(QWidget):
    """Reusable settings form widget."""

    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._build_ui()
        self._load_current()
        self._connect_signals()

    def reload(self) -> None:
        """Re-load current config values into the form."""
        self._load_current()

    # ── Shared styles ────────────────────────────────────

    @staticmethod
    def _css(extra: str = "") -> str:
        return f"font-family: 'Segoe UI'; background: transparent; {extra}"

    _INPUT_CSS = (
        "QLineEdit, QComboBox, QSpinBox {"
        "  background: #2a2a3e; color: #e0e0e0; border: 1px solid #444;"
        "  border-radius: 6px; padding: 6px 10px;"
        "  font-family: 'Segoe UI'; font-size: 10pt;"
        "}"
        "QLineEdit:focus, QComboBox:focus, QSpinBox:focus {"
        "  border-color: #5b8def;"
        "}"
        "QComboBox {"
        "  padding-right: 24px;"
        "}"
        "QComboBox::drop-down {"
        "  subcontrol-origin: padding;"
        "  subcontrol-position: top right;"
        "  width: 22px;"
        "  border: none;"
        "}"
        "QComboBox::down-arrow {"
        "  image: none;"
        "  width: 0px;"
        "  height: 0px;"
        "  border-left: 4px solid transparent;"
        "  border-right: 4px solid transparent;"
        "  border-top: 5px solid #8888aa;"
        "  margin-right: 6px;"
        "}"
        "QComboBox::down-arrow:hover {"
        "  border-top: 5px solid #5b8def;"
        "}"
        "QComboBox QAbstractItemView {"
        "  background: #2a2a3e; color: #e0e0e0;"
        "  selection-background-color: #3a3a5c;"
        "  border: 1px solid #444;"
        "}"
    )

    _GROUP_CSS = (
        "QGroupBox {"
        "  color: #bbb; border: 1px solid #3a3a4e;"
        "  border-radius: 8px; margin-top: 12px; padding: 14px 12px 10px;"
        "  font-family: 'Segoe UI'; font-size: 10pt; font-weight: 600;"
        "}"
        "QGroupBox::title {"
        "  subcontrol-origin: margin; left: 14px; padding: 0 6px;"
        "}"
    )

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── API Key & Provider section ──
        grp_key = QGroupBox("API-ключ и провайдеры")
        grp_key.setStyleSheet(self._GROUP_CSS)
        key_layout = QVBoxLayout(grp_key)
        key_layout.setSpacing(8)

        lbl_prov = QLabel("Основной провайдер:")
        lbl_prov.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        key_layout.addWidget(lbl_prov)

        prov_row = QHBoxLayout()
        self._radio_group = QButtonGroup(self)
        self._radio_or = QRadioButton("OpenRouter")
        self._radio_ant = QRadioButton("Anthropic")
        self._radio_group.addButton(self._radio_or, 0)
        self._radio_group.addButton(self._radio_ant, 1)
        radio_css = self._css("color: #ccc; font-size: 9pt;")
        self._radio_or.setStyleSheet(radio_css)
        self._radio_ant.setStyleSheet(radio_css)
        prov_row.addWidget(self._radio_or)
        prov_row.addWidget(self._radio_ant)
        key_layout.addLayout(prov_row)

        self._chk_fallback = QCheckBox("Автоматически переключаться на резервный провайдер при сбое (Fallback)")
        self._chk_fallback.setStyleSheet(self._css("color: #ccc; font-size: 9pt;"))
        key_layout.addWidget(self._chk_fallback)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("Новый API-ключ для выбранного провайдера (оставьте пустым, если не меняется)")
        self._key_input.setStyleSheet(self._INPUT_CSS)
        key_layout.addWidget(self._key_input)

        self._key_status = QLabel("")
        self._key_status.setWordWrap(True)
        self._key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        key_layout.addWidget(self._key_status)

        layout.addWidget(grp_key)

        # ── Translation backend section ──
        grp_backend = QGroupBox("Бэкенд перевода")
        grp_backend.setStyleSheet(self._GROUP_CSS)
        backend_layout = QVBoxLayout(grp_backend)
        backend_layout.setSpacing(8)

        lbl_backend = QLabel("Чем выполнять перевод:")
        lbl_backend.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        backend_layout.addWidget(lbl_backend)

        # Backend combo (replaces the old pair of radio buttons).
        from translate.backend import BACKENDS as _ALL_BACKENDS
        self._backend_combo = QComboBox()
        self._backend_combo.setStyleSheet(self._INPUT_CSS)
        for bid, blabel in _ALL_BACKENDS:
            self._backend_combo.addItem(blabel, bid)
        backend_layout.addWidget(self._backend_combo)

        # ── NLLB-specific widgets (hidden when another backend is active) ──
        self._nllb_container = QWidget()
        nllb_inner = QVBoxLayout(self._nllb_container)
        nllb_inner.setContentsMargins(0, 4, 0, 0)
        nllb_inner.setSpacing(6)

        # Optional explicit model path (empty = auto-discover).
        nllb_path_row = QHBoxLayout()
        lbl_nllb_path = QLabel("Путь к модели:")
        lbl_nllb_path.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        self._nllb_path_edit = QLineEdit()
        self._nllb_path_edit.setPlaceholderText(
            "оставьте пустым для автопоиска (…/models/nllb-200-ct2-int8)"
        )
        self._nllb_path_edit.setStyleSheet(self._INPUT_CSS)
        nllb_path_row.addWidget(lbl_nllb_path)
        nllb_path_row.addWidget(self._nllb_path_edit, 1)
        nllb_inner.addLayout(nllb_path_row)

        status_row = QHBoxLayout()
        self._nllb_status = QLabel("")
        self._nllb_status.setWordWrap(True)
        self._nllb_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        status_row.addWidget(self._nllb_status, 1)

        self._btn_load_nllb = QPushButton("Загрузить модель")
        self._btn_load_nllb.setCursor(Qt.PointingHandCursor)
        self._btn_load_nllb.setToolTip("Проверить наличие модели и прогреть её в памяти")
        self._btn_load_nllb.setStyleSheet(
            "QPushButton {"
            "  background: #2a2a3e; color: #5b8def; border: 1px solid #5b8def;"
            "  border-radius: 6px; padding: 6px 14px;"
            "  font-family: 'Segoe UI'; font-size: 9pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #3a3a5c; color: #7ca5f5; }"
            "QPushButton:disabled { background: #1f1f2e; color: #555; border-color: #333; }"
        )
        self._btn_load_nllb.clicked.connect(self._on_load_nllb_clicked)
        status_row.addWidget(self._btn_load_nllb)
        nllb_inner.addLayout(status_row)

        backend_layout.addWidget(self._nllb_container)

        self._backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        layout.addWidget(grp_backend)

        # ── NMT API keys section ──
        grp_nmt = QGroupBox("Ключи быстрых переводчиков")
        grp_nmt.setStyleSheet(self._GROUP_CSS)
        nmt_layout = QVBoxLayout(grp_nmt)
        nmt_layout.setSpacing(10)

        nmt_btn_css = (
            "QPushButton {"
            "  background: #2a2a3e; color: #5b8def; border: 1px solid #5b8def;"
            "  border-radius: 6px; padding: 5px 12px;"
            "  font-family: 'Segoe UI'; font-size: 9pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #3a3a5c; color: #7ca5f5; }"
            "QPushButton:disabled { background: #1f1f2e; color: #555; border-color: #333; }"
        )

        # ── Google API Key ──
        lbl_google = QLabel("Google API Key")
        lbl_google.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        nmt_layout.addWidget(lbl_google)
        lbl_google_hint = QLabel("Необязательно — без ключа работает через бесплатный Web RPC")
        lbl_google_hint.setStyleSheet(self._css("color: #888; font-size: 8.5pt;"))
        nmt_layout.addWidget(lbl_google_hint)

        google_row = QHBoxLayout()
        self._google_key_input = QLineEdit()
        self._google_key_input.setPlaceholderText("AIza...")
        self._google_key_input.setEchoMode(QLineEdit.Password)
        self._google_key_input.setStyleSheet(self._INPUT_CSS)
        google_row.addWidget(self._google_key_input, 1)

        self._btn_save_google = QPushButton("Сохранить")
        self._btn_save_google.setStyleSheet(nmt_btn_css)
        self._btn_save_google.setCursor(Qt.PointingHandCursor)
        self._btn_save_google.clicked.connect(lambda: self._save_nmt_key("google"))
        google_row.addWidget(self._btn_save_google)

        self._btn_test_google = QPushButton("Проверить")
        self._btn_test_google.setStyleSheet(nmt_btn_css)
        self._btn_test_google.setCursor(Qt.PointingHandCursor)
        self._btn_test_google.clicked.connect(lambda: self._test_nmt_key("google"))
        google_row.addWidget(self._btn_test_google)
        nmt_layout.addLayout(google_row)

        self._google_key_status = QLabel("")
        self._google_key_status.setWordWrap(True)
        self._google_key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        nmt_layout.addWidget(self._google_key_status)

        # ── DeepL API Key ──
        lbl_deepl = QLabel("DeepL API Key")
        lbl_deepl.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        nmt_layout.addWidget(lbl_deepl)
        lbl_deepl_hint = QLabel("Free или Pro ключ (суффикс :fx = Free)")
        lbl_deepl_hint.setStyleSheet(self._css("color: #888; font-size: 8.5pt;"))
        nmt_layout.addWidget(lbl_deepl_hint)

        deepl_row = QHBoxLayout()
        self._deepl_key_input = QLineEdit()
        self._deepl_key_input.setPlaceholderText("xxxxxxxx-xxxx-...:fx")
        self._deepl_key_input.setEchoMode(QLineEdit.Password)
        self._deepl_key_input.setStyleSheet(self._INPUT_CSS)
        deepl_row.addWidget(self._deepl_key_input, 1)

        self._btn_save_deepl = QPushButton("Сохранить")
        self._btn_save_deepl.setStyleSheet(nmt_btn_css)
        self._btn_save_deepl.setCursor(Qt.PointingHandCursor)
        self._btn_save_deepl.clicked.connect(lambda: self._save_nmt_key("deepl"))
        deepl_row.addWidget(self._btn_save_deepl)

        self._btn_test_deepl = QPushButton("Проверить")
        self._btn_test_deepl.setStyleSheet(nmt_btn_css)
        self._btn_test_deepl.setCursor(Qt.PointingHandCursor)
        self._btn_test_deepl.clicked.connect(lambda: self._test_nmt_key("deepl"))
        deepl_row.addWidget(self._btn_test_deepl)
        nmt_layout.addLayout(deepl_row)

        self._deepl_key_status = QLabel("")
        self._deepl_key_status.setWordWrap(True)
        self._deepl_key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        nmt_layout.addWidget(self._deepl_key_status)

        # ── Azure Translator Key + Region ──
        lbl_azure = QLabel("Azure Translator Key")
        lbl_azure.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        nmt_layout.addWidget(lbl_azure)

        azure_row = QHBoxLayout()
        self._azure_key_input = QLineEdit()
        self._azure_key_input.setPlaceholderText("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._azure_key_input.setEchoMode(QLineEdit.Password)
        self._azure_key_input.setStyleSheet(self._INPUT_CSS)
        azure_row.addWidget(self._azure_key_input, 1)

        self._btn_save_azure = QPushButton("Сохранить")
        self._btn_save_azure.setStyleSheet(nmt_btn_css)
        self._btn_save_azure.setCursor(Qt.PointingHandCursor)
        self._btn_save_azure.clicked.connect(lambda: self._save_nmt_key("azure"))
        azure_row.addWidget(self._btn_save_azure)

        self._btn_test_azure = QPushButton("Проверить")
        self._btn_test_azure.setStyleSheet(nmt_btn_css)
        self._btn_test_azure.setCursor(Qt.PointingHandCursor)
        self._btn_test_azure.clicked.connect(lambda: self._test_nmt_key("azure"))
        azure_row.addWidget(self._btn_test_azure)
        nmt_layout.addLayout(azure_row)

        azure_region_row = QHBoxLayout()
        lbl_azure_region = QLabel("Регион:")
        lbl_azure_region.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        self._azure_region_input = QLineEdit()
        self._azure_region_input.setPlaceholderText("global")
        self._azure_region_input.setStyleSheet(self._INPUT_CSS)
        azure_region_row.addWidget(lbl_azure_region)
        azure_region_row.addWidget(self._azure_region_input, 1)
        nmt_layout.addLayout(azure_region_row)

        self._azure_key_status = QLabel("")
        self._azure_key_status.setWordWrap(True)
        self._azure_key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        nmt_layout.addWidget(self._azure_key_status)

        layout.addWidget(grp_nmt)

        # ── OCR GPU acceleration ──
        grp_ocr_gpu = QGroupBox("Ускорение OCR (видеокарта)")
        grp_ocr_gpu.setStyleSheet(self._GROUP_CSS)
        ocr_gpu_layout = QVBoxLayout(grp_ocr_gpu)
        ocr_gpu_layout.setSpacing(8)

        # GPU info label
        gpu_info = self._detect_gpu_info()
        self._gpu_info_label = QLabel(gpu_info)
        self._gpu_info_label.setWordWrap(True)
        self._gpu_info_label.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        ocr_gpu_layout.addWidget(self._gpu_info_label)

        gpu_mode_row = QHBoxLayout()
        lbl_gpu_mode = QLabel("Режим GPU для EasyOCR:")
        lbl_gpu_mode.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; font-weight: 600;"))
        gpu_mode_row.addWidget(lbl_gpu_mode)

        self._ocr_gpu_combo = QComboBox()
        self._ocr_gpu_combo.setStyleSheet(self._INPUT_CSS)
        self._ocr_gpu_combo.addItem("Авто (GPU при наличии свободной VRAM ≥ 450 МБ)", "auto")
        self._ocr_gpu_combo.addItem("Только видеокарта (CUDA)", "gpu")
        self._ocr_gpu_combo.addItem("Только процессор (CPU)", "cpu")
        gpu_mode_row.addWidget(self._ocr_gpu_combo, 1)
        ocr_gpu_layout.addLayout(gpu_mode_row)

        layout.addWidget(grp_ocr_gpu)

        # ── Translation section ──
        grp_trans = QGroupBox("Перевод")
        grp_trans.setStyleSheet(self._GROUP_CSS)
        trans_layout = QVBoxLayout(grp_trans)
        trans_layout.setSpacing(8)

        # Context / Domain
        domain_row = QHBoxLayout()
        lbl_domain = QLabel("Контекст перевода:")
        lbl_domain.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._domain_combo = QComboBox()
        self._domain_combo.setStyleSheet(self._INPUT_CSS)
        from translate.domain_manager import list_available_domains
        for d in list_available_domains():
            self._domain_combo.addItem(f"{d['display_name']} ({d['id']})", d["id"])
        domain_row.addWidget(lbl_domain)
        domain_row.addWidget(self._domain_combo, 1)
        trans_layout.addLayout(domain_row)

        # Source language
        src_lang_row = QHBoxLayout()
        lbl_src_lang = QLabel("Исходный язык:")
        lbl_src_lang.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._src_lang_combo = QComboBox()
        self._src_lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _SOURCE_LANGUAGES:
            self._src_lang_combo.addItem(f"{name} ({code})", code)
        src_lang_row.addWidget(lbl_src_lang)
        src_lang_row.addWidget(self._src_lang_combo, 1)
        trans_layout.addLayout(src_lang_row)

        # Target language
        lang_row = QHBoxLayout()
        lbl_lang = QLabel("Язык перевода:")
        lbl_lang.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _TARGET_LANGUAGES:
            self._lang_combo.addItem(f"{name} ({code})", code)
        lang_row.addWidget(lbl_lang)
        lang_row.addWidget(self._lang_combo, 1)
        trans_layout.addLayout(lang_row)

        # Translation engine
        engine_row = QHBoxLayout()
        lbl_engine = QLabel("Движок перевода:")
        lbl_engine.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._engine_combo = QComboBox()
        self._engine_combo.setStyleSheet(self._INPUT_CSS)
        for eng_id, eng_label in _ENGINES:
            self._engine_combo.addItem(eng_label, eng_id)
        engine_row.addWidget(lbl_engine)
        engine_row.addWidget(self._engine_combo, 1)
        trans_layout.addLayout(engine_row)

        # LLM model — Standard clean dropdown matching other settings + custom model field
        model_row = QHBoxLayout()
        lbl_model = QLabel("LLM-модель:")
        lbl_model.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))

        self._model_combo = QComboBox()
        self._model_combo.setEditable(False)
        self._model_combo.setMaxVisibleItems(10)
        self._model_combo.setStyleSheet(self._INPUT_CSS)
        self._populate_model_combo()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)

        model_row.addWidget(lbl_model)
        model_row.addWidget(self._model_combo, 1)
        trans_layout.addLayout(model_row)

        # Custom model input (visible only when "Другая модель..." is selected)
        self._custom_model_row_widget = QWidget()
        custom_row_layout = QHBoxLayout(self._custom_model_row_widget)
        custom_row_layout.setContentsMargins(0, 2, 0, 2)
        lbl_custom_model = QLabel("ID модели:")
        lbl_custom_model.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        self._custom_model_edit = QLineEdit()
        self._custom_model_edit.setPlaceholderText("например: meta-llama/llama-3.3-70b-instruct")
        self._custom_model_edit.setStyleSheet(self._INPUT_CSS)
        custom_row_layout.addWidget(lbl_custom_model)
        custom_row_layout.addWidget(self._custom_model_edit, 1)
        self._custom_model_row_widget.setVisible(False)
        trans_layout.addWidget(self._custom_model_row_widget)

        # B3: hint label
        self._model_hint = QLabel("")
        self._model_hint.setStyleSheet(self._css("color: #666; font-size: 8.5pt; font-style: italic; padding-left: 2px;"))
        self._model_hint.setWordWrap(True)
        trans_layout.addWidget(self._model_hint)

        # Streaming checkbox
        self._chk_streaming = QCheckBox("Потоковый вывод перевода (Streaming)")
        self._chk_streaming.setToolTip("Выводить перевод слово за словом сразу по мере генерации ответа моделью")
        self._chk_streaming.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; margin-top: 4px;"))
        trans_layout.addWidget(self._chk_streaming)

        # Compact prompt checkbox
        self._chk_compact_prompt = QCheckBox("Компактный системный промпт (ускорение отклика)")
        self._chk_compact_prompt.setToolTip("Сокращает служебные инструкции запроса, ускоряя начало ответа модели на ~30–50%")
        self._chk_compact_prompt.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; margin-top: 2px;"))
        trans_layout.addWidget(self._chk_compact_prompt)

        # D1: OCR preview checkbox
        self._chk_ocr_preview = QCheckBox("Предпросмотр и правка OCR-текста перед переводом")
        self._chk_ocr_preview.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; margin-top: 2px;"))
        trans_layout.addWidget(self._chk_ocr_preview)

        # Max tokens row
        tokens_row = QHBoxLayout()
        lbl_tokens = QLabel("Макс. токенов ответа:")
        lbl_tokens.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._tokens_spin = QSpinBox()
        self._tokens_spin.setRange(50, 2000)
        self._tokens_spin.setSingleStep(50)
        self._tokens_spin.setSuffix(" токенов")
        self._tokens_spin.setStyleSheet(self._INPUT_CSS)
        tokens_row.addWidget(lbl_tokens)
        tokens_row.addWidget(self._tokens_spin, 1)
        trans_layout.addLayout(tokens_row)

        # Popup timeout
        timeout_row = QHBoxLayout()
        lbl_timeout = QLabel("Автоскрытие попапа (сек):")
        lbl_timeout.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(3, 60)
        self._timeout_spin.setSuffix(" сек")
        self._timeout_spin.setStyleSheet(self._INPUT_CSS)
        timeout_row.addWidget(lbl_timeout)
        timeout_row.addWidget(self._timeout_spin, 1)
        trans_layout.addLayout(timeout_row)

        layout.addWidget(grp_trans)

        # ── Custom Profiles section ("Мои профили") ──
        grp_custom = QGroupBox("Мои профили контекста")
        grp_custom.setStyleSheet(self._GROUP_CSS)
        custom_layout = QVBoxLayout(grp_custom)
        custom_layout.setSpacing(8)

        c_head = QHBoxLayout()
        lbl_c_desc = QLabel("Кастомные промпты и словари для адаптивного перевода:")
        lbl_c_desc.setStyleSheet(self._css("color: #aaa; font-size: 9pt;"))
        c_head.addWidget(lbl_c_desc)
        c_head.addStretch()

        self._btn_create_profile = QPushButton("➕ Создать новый профиль")
        self._btn_create_profile.setCursor(Qt.PointingHandCursor)
        self._btn_create_profile.setStyleSheet(
            "QPushButton {"
            "  background: #2a2a3e; color: #5b8def; border: 1px solid #5b8def;"
            "  border-radius: 6px; padding: 6px 14px;"
            "  font-family: 'Segoe UI'; font-size: 9pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #3a3a5c; color: #7ca5f5; }"
        )
        self._btn_create_profile.clicked.connect(self._on_create_profile)
        c_head.addWidget(self._btn_create_profile)
        custom_layout.addLayout(c_head)

        self._custom_profiles_container = QWidget()
        self._custom_profiles_layout = QVBoxLayout(self._custom_profiles_container)
        self._custom_profiles_layout.setContentsMargins(0, 4, 0, 0)
        self._custom_profiles_layout.setSpacing(6)
        custom_layout.addWidget(self._custom_profiles_container)

        layout.addWidget(grp_custom)

        # ── Notifications section ──
        grp_notify = QGroupBox("Уведомления")
        grp_notify.setStyleSheet(self._GROUP_CSS)
        notify_layout = QVBoxLayout(grp_notify)
        notify_layout.setSpacing(6)

        self._radio_notify_group = QButtonGroup(self)
        self._radio_popup = QRadioButton("Показывать результат в попап-окне")
        self._radio_toast = QRadioButton("Показывать через системные уведомления Windows")
        self._radio_notify_group.addButton(self._radio_popup, 0)
        self._radio_notify_group.addButton(self._radio_toast, 1)
        self._radio_popup.setStyleSheet(radio_css)
        self._radio_toast.setStyleSheet(radio_css)
        notify_layout.addWidget(self._radio_popup)
        notify_layout.addWidget(self._radio_toast)

        layout.addWidget(grp_notify)

        # ── About & Updates section ──
        grp_about = QGroupBox("О программе и обновления")
        grp_about.setStyleSheet(self._GROUP_CSS)
        about_layout = QVBoxLayout(grp_about)
        about_layout.setSpacing(8)

        ver_row = QHBoxLayout()
        self._lbl_ver = QLabel(f"Версия приложения: v{getattr(config, 'APP_VERSION', '1.0.0')}")
        self._lbl_ver.setStyleSheet(self._css("color: #ccc; font-size: 10pt; font-weight: 600;"))
        ver_row.addWidget(self._lbl_ver)
        ver_row.addStretch()

        self._btn_check_update = QPushButton("Проверить обновления")
        self._btn_check_update.setStyleSheet(
            "QPushButton {"
            "  background: #2a2a3e; color: #5b8def; border: 1px solid #5b8def;"
            "  border-radius: 6px; padding: 6px 14px;"
            "  font-family: 'Segoe UI'; font-size: 9.5pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #3a3a5c; color: #7ca5f5; }"
            "QPushButton:disabled { background: #1f1f2e; color: #555; border-color: #333; }"
        )
        ver_row.addWidget(self._btn_check_update)
        about_layout.addLayout(ver_row)

        self._update_status_lbl = QLabel("")
        self._update_status_lbl.setWordWrap(True)
        self._update_status_lbl.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        about_layout.addWidget(self._update_status_lbl)

        layout.addWidget(grp_about)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setStyleSheet(
            "QPushButton {"
            "  background: #5b8def; color: #fff; border: none;"
            "  border-radius: 6px; padding: 9px 24px;"
            "  font-family: 'Segoe UI'; font-size: 10pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a7de0; }"
            "QPushButton:disabled { background: #3a3a5c; color: #666; }"
        )

        btn_row.addStretch()
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

    # ── Custom profiles list management ─────────────────

    def _reload_custom_profiles_list(self):
        while self._custom_profiles_layout.count():
            item = self._custom_profiles_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        from translate.domain_manager import list_available_domains
        all_domains = list_available_domains()
        custom_domains = [d for d in all_domains if d.get("is_custom")]

        if not custom_domains:
            empty_lbl = QLabel("У вас пока нет пользовательских профилей.")
            empty_lbl.setStyleSheet(self._css("color: #777799; font-size: 9pt; font-style: italic;"))
            self._custom_profiles_layout.addWidget(empty_lbl)
            return

        for dom in custom_domains:
            dom_id = dom["id"]
            display_name = dom["display_name"]

            row = QFrame()
            row.setStyleSheet(
                "QFrame {"
                "  background: #232334; border: 1px solid #3a3a4e;"
                "  border-radius: 6px; padding: 4px 8px;"
                "}"
            )
            r_layout = QHBoxLayout(row)
            r_layout.setContentsMargins(8, 6, 8, 6)

            lbl = QLabel(f"<b>{display_name}</b> <span style='color:#777; font-size:8.5pt;'>({dom_id})</span>")
            lbl.setStyleSheet(self._css("color: #e0e0e0; font-size: 9.5pt;"))
            r_layout.addWidget(lbl)
            r_layout.addStretch()

            btn_edit = QPushButton("✏️ Редактировать")
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #aaa; border: 1px solid #444;"
                "  border-radius: 4px; padding: 4px 10px; font-family: 'Segoe UI'; font-size: 8.5pt;"
                "}"
                "QPushButton:hover { background: #2a2a3e; color: #fff; }"
            )
            btn_edit.clicked.connect(lambda _, did=dom_id: self._on_edit_profile(did))
            r_layout.addWidget(btn_edit)

            btn_del = QPushButton("🗑️ Удалить")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #ff6b6b; border: 1px solid #663333;"
                "  border-radius: 4px; padding: 4px 10px; font-family: 'Segoe UI'; font-size: 8.5pt;"
                "}"
                "QPushButton:hover { background: rgba(255, 107, 107, 0.15); color: #ff8888; }"
            )
            btn_del.clicked.connect(lambda _, did=dom_id, dname=display_name: self._on_delete_profile(did, dname))
            r_layout.addWidget(btn_del)

            self._custom_profiles_layout.addWidget(row)

    def _refresh_all_domain_combos(self):
        """Re-populate domain combos in SettingsWidget and MainWindow."""
        from translate.domain_manager import list_available_domains
        self._domain_combo.blockSignals(True)
        self._domain_combo.clear()
        for d in list_available_domains():
            self._domain_combo.addItem(f"{d['display_name']} ({d['id']})", d["id"])
        idx = self._domain_combo.findData(config.ACTIVE_DOMAIN)
        if idx >= 0:
            self._domain_combo.setCurrentIndex(idx)
        self._domain_combo.blockSignals(False)

        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, "_home_page") and hasattr(widget._home_page, "_domain_combo"):
                widget._home_page._domain_combo.blockSignals(True)
                widget._home_page._domain_combo.clear()
                for d in list_available_domains():
                    widget._home_page._domain_combo.addItem(f"{d['display_name']} ({d['id']})", d["id"])
                idx_h = widget._home_page._domain_combo.findData(config.ACTIVE_DOMAIN)
                if idx_h >= 0:
                    widget._home_page._domain_combo.setCurrentIndex(idx_h)
                widget._home_page._domain_combo.blockSignals(False)

    def _on_create_profile(self):
        dlg = ProfileEditorDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_custom_profiles_list()
            self._refresh_all_domain_combos()

    def _on_edit_profile(self, domain_id: str):
        from translate.domain_manager import load_domain_profile
        data = load_domain_profile(domain_id)
        dlg = ProfileEditorDialog(self, data)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_custom_profiles_list()
            self._refresh_all_domain_combos()

    def _on_delete_profile(self, domain_id: str, display_name: str):
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы действительно хотите удалить пользовательский профиль '{display_name}' ({domain_id})?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            from translate.domain_manager import delete_custom_profile
            delete_custom_profile(domain_id)
            if config.ACTIVE_DOMAIN == domain_id:
                config.ACTIVE_DOMAIN = "general"
            self._reload_custom_profiles_list()
            self._refresh_all_domain_combos()

    # ── Model combo helpers (B1/B2/B3) ───────────────────

    def _populate_model_combo(self, models: list[tuple[str, str]] | None = None) -> None:
        """Fill the model QComboBox from *models* (or the default _OPENROUTER_MODELS)."""
        source = models if models is not None else _OPENROUTER_MODELS
        saved_data = self._model_combo.currentData() if self._model_combo.count() > 0 else None
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model_id, display in source:
            self._model_combo.addItem(display, model_id)
        self._model_combo.blockSignals(False)

        # Restore previously selected value
        if saved_data:
            found = self._model_combo.findData(saved_data)
            if found >= 0:
                self._model_combo.setCurrentIndex(found)

    @staticmethod
    def _detect_gpu_info() -> str:
        """Return a human-readable string about the detected GPU."""
        try:
            import torch
            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                name = torch.cuda.get_device_name(0)
                total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                free_mb = 0.0
                try:
                    free, _ = torch.cuda.mem_get_info(0)
                    free_mb = free / (1024 ** 2)
                except Exception:
                    pass
                info = f"✓ Обнаружена: {name} ({total:.1f} ГБ)"
                if free_mb > 0:
                    info += f" — свободно {free_mb:.0f} МБ"
                return info
            return "CUDA недоступна — EasyOCR будет работать на CPU"
        except ImportError:
            return "PyTorch не установлен — EasyOCR будет работать на CPU"
        except Exception as e:
            return f"Не удалось определить GPU: {e}"

    def _on_model_changed(self, index: int) -> None:
        """Show a short hint below the combo and toggle the custom model field."""
        model_id = self._model_combo.itemData(index)
        is_custom = (model_id == "__custom__")
        if hasattr(self, "_custom_model_row_widget"):
            self._custom_model_row_widget.setVisible(is_custom)
        hint = _MODEL_HINTS.get(str(model_id), "")
        self._model_hint.setText(hint)

    # ── NMT key management ────────────────────────────────

    def _nmt_status_label(self, provider: str) -> QLabel:
        """Return the status QLabel for the given NMT provider."""
        return {
            "google": self._google_key_status,
            "deepl":  self._deepl_key_status,
            "azure":  self._azure_key_status,
        }[provider]

    def _nmt_key_input(self, provider: str) -> QLineEdit:
        """Return the key QLineEdit for the given NMT provider."""
        return {
            "google": self._google_key_input,
            "deepl":  self._deepl_key_input,
            "azure":  self._azure_key_input,
        }[provider]

    def _save_nmt_key(self, provider: str) -> None:
        """Save an NMT API key to keyring."""
        key_text = self._nmt_key_input(provider).text().strip()
        status = self._nmt_status_label(provider)

        if not key_text:
            status.setText("Введите ключ.")
            status.setStyleSheet(self._css("color: #ff6b6b; font-size: 9pt;"))
            return

        try:
            settings.set_api_key(provider, key_text)
        except Exception as e:
            status.setText(f"Ошибка сохранения: {e}")
            status.setStyleSheet(self._css("color: #ff6b6b; font-size: 9pt;"))
            return

        # Also persist azure_region when saving azure key.
        if provider == "azure":
            region = self._azure_region_input.text().strip() or "global"
            config_manager.set_value("azure_region", region)

        status.setText(f"✓ Ключ {provider} сохранён!")
        status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
        self._nmt_key_input(provider).clear()
        self._refresh_nmt_key_status()

    def _test_nmt_key(self, provider: str) -> None:
        """Send a test phrase through the NMT backend and show the result."""
        status = self._nmt_status_label(provider)
        status.setText("Проверяем…")
        status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        QApplication.processEvents()

        # Temporarily persist azure_region so the test picks it up.
        if provider == "azure":
            region = self._azure_region_input.text().strip() or "global"
            config_manager.set_value("azure_region", region)

        try:
            from translate.backend import _get_nmt_client
            client = _get_nmt_client(provider)
            detected, translated = client.translate("Hello world", target_lang="ru")
            status.setText(f"✓ {detected} → ru: «{translated}»")
            status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
        except Exception as e:
            status.setText(f"✗ {e}")
            status.setStyleSheet(self._css("color: #ff6b6b; font-size: 9pt;"))

    def _refresh_nmt_key_status(self) -> None:
        """Update NMT key status labels based on what's stored in keyring."""
        _nmt_providers = [
            ("google", self._google_key_status, "Google"),
            ("deepl",  self._deepl_key_status,  "DeepL"),
            ("azure",  self._azure_key_status,   "Azure"),
        ]
        for provider, label, name in _nmt_providers:
            has_key = bool(settings.get_api_key(provider))
            if has_key:
                label.setText(f"✓ Ключ {name} сохранён в Keyring")
                label.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
            else:
                if provider == "google":
                    label.setText("Ключ не задан — будет использоваться бесплатный Web RPC")
                else:
                    label.setText(f"Ключ {name} не задан")
                label.setStyleSheet(self._css("color: #999; font-size: 9pt;"))

        # Azure region.
        self._azure_region_input.setText(config_manager.get("azure_region") or "global")

    # ── Load current values ──────────────────────────────

    # ── Translation backend (API / local NLLB) ──────────

    def _set_nllb_status(self, message: str, *, color: str = "#999") -> None:
        self._nllb_status.setText(message)
        self._nllb_status.setStyleSheet(self._css(f"color: {color}; font-size: 9pt;"))

    def _refresh_nllb_status(self) -> None:
        """Show whether the local model is present, without loading it."""
        from translate.backend import BACKEND_NLLB
        use_nllb = self._backend_combo.currentData() == BACKEND_NLLB
        self._nllb_container.setVisible(use_nllb)

        if not use_nllb:
            return

        from translate.nllb_backend import get_backend, resolve_model_dir

        backend = get_backend()
        if backend.is_loaded:
            self._set_nllb_status(
                f"✓ Модель загружена в память: {backend.model_dir}", color="#66cc99"
            )
            return

        found = resolve_model_dir()
        if found is not None:
            self._set_nllb_status(
                f"✓ Модель найдена: {found}\nБудет загружена при первом переводе "
                "(или нажмите «Загрузить модель»).",
                color="#66cc99",
            )
        else:
            self._set_nllb_status(
                "⚠ Локальная модель NLLB не найдена. Укажите путь к каталогу "
                "nllb-200-ct2-int8 выше либо сконвертируйте модель "
                "(ct2-transformers-converter). Пока модель недоступна, перевод "
                "будет выполняться через API.",
                color="#ffb347",
            )

    def _on_backend_changed(self, _index=None) -> None:
        """React to backend combo change: show/hide NLLB block, refresh status."""
        from translate.backend import BACKEND_NLLB
        if self._backend_combo.currentData() == BACKEND_NLLB:
            path_text = self._nllb_path_edit.text().strip()
            if path_text != (getattr(config, "NLLB_MODEL_PATH", "") or ""):
                # Preview the typed path without persisting it yet.
                from translate.nllb_backend import reset_client as reset_nllb
                reset_nllb()
        self._refresh_nllb_status()

    def _on_load_nllb_clicked(self) -> None:
        """Persist the path, then load the model in the background with an indicator."""
        config_manager.set_value("nllb_model_path", self._nllb_path_edit.text().strip())

        from translate.nllb_backend import reset_client as reset_nllb
        reset_nllb()

        self._btn_load_nllb.setEnabled(False)
        self._set_nllb_status("⏳ Загрузка локальной модели… (около 600 МБ, 1–5 с)")
        QApplication.processEvents()

        self._nllb_worker = _NllbPreloadWorker(self)
        self._nllb_worker.finished_with_status.connect(self._on_nllb_preload_done)
        self._nllb_worker.start()

    def _on_nllb_preload_done(self, ok: bool, message: str) -> None:
        from translate.backend import BACKEND_NLLB
        self._btn_load_nllb.setEnabled(self._backend_combo.currentData() == BACKEND_NLLB)
        if ok:
            self._set_nllb_status(f"✓ {message}", color="#66cc99")
        else:
            self._set_nllb_status(
                f"⚠ {message}\n\nПока модель недоступна, перевод будет "
                "выполняться через API.",
                color="#ffb347",
            )

    # ── Load ─────────────────────────────────────────────

    def _load_current(self) -> None:

        # Translation backend (combo box).
        current_backend = getattr(config, "TRANSLATION_BACKEND", "api") or "api"
        for i in range(self._backend_combo.count()):
            if self._backend_combo.itemData(i) == current_backend:
                self._backend_combo.setCurrentIndex(i)
                break
        self._nllb_path_edit.setText(getattr(config, "NLLB_MODEL_PATH", "") or "")
        self._refresh_nllb_status()

        # NMT key statuses (Google / DeepL / Azure).
        self._refresh_nmt_key_status()

        # OCR GPU mode.
        ocr_gpu_mode = getattr(config, "OCR_GPU_MODE", "auto") or "auto"
        for i in range(self._ocr_gpu_combo.count()):
            if self._ocr_gpu_combo.itemData(i) == ocr_gpu_mode:
                self._ocr_gpu_combo.setCurrentIndex(i)
                break

        # Primary provider choice & Fallback setting.
        primary = settings.get_primary_provider()
        if primary == "anthropic":
            self._radio_ant.setChecked(True)
        else:
            self._radio_or.setChecked(True)

        self._chk_fallback.setChecked(settings.is_fallback_enabled())

        has_or = bool(settings.get_api_key("openrouter"))
        has_ant = bool(settings.get_api_key("anthropic"))

        status_parts = []
        if has_or:
            status_parts.append("OpenRouter ✓")
        if has_ant:
            status_parts.append("Anthropic ✓")

        if status_parts:
            self._key_status.setText("Сохранённые ключи: " + ", ".join(status_parts))
            self._key_status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
        else:
            self._key_status.setText("Ключи не заданы в Keyring (используются переменные из .env)")
            self._key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))

        # Domain.
        self._refresh_all_domain_combos()

        # Custom profiles list.
        self._reload_custom_profiles_list()

        # Source language.
        idx_src = self._src_lang_combo.findData(config.SOURCE_LANG)
        if idx_src >= 0:
            self._src_lang_combo.setCurrentIndex(idx_src)

        # Target language.
        idx = self._lang_combo.findData(config.TARGET_LANG)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        # Translation engine.
        idx_eng = self._engine_combo.findData(config.TRANSLATION_ENGINE)
        if idx_eng >= 0:
            self._engine_combo.setCurrentIndex(idx_eng)

        # LLM model — select preset or enable custom model field
        current_model = config.LLM_MODEL or "openai/gpt-oss-20b:free"
        found_idx = self._model_combo.findData(current_model)
        if found_idx >= 0 and current_model != "__custom__":
            self._model_combo.setCurrentIndex(found_idx)
            if hasattr(self, "_custom_model_row_widget"):
                self._custom_model_row_widget.setVisible(False)
        else:
            custom_idx = self._model_combo.findData("__custom__")
            if custom_idx >= 0:
                self._model_combo.setCurrentIndex(custom_idx)
            if hasattr(self, "_custom_model_edit"):
                self._custom_model_edit.setText(current_model)
            if hasattr(self, "_custom_model_row_widget"):
                self._custom_model_row_widget.setVisible(True)
        self._on_model_changed(self._model_combo.currentIndex())  # update hint

        # Translation options
        self._chk_streaming.setChecked(bool(getattr(config, "ENABLE_STREAMING", True)))
        self._chk_compact_prompt.setChecked(bool(getattr(config, "COMPACT_PROMPT", True)))
        self._chk_ocr_preview.setChecked(bool(getattr(config, "ENABLE_OCR_PREVIEW", False)))
        self._tokens_spin.setValue(int(getattr(config, "LLM_MAX_TOKENS", 350)))

        # Popup timeout.
        self._timeout_spin.setValue(config.POPUP_TIMEOUT_SEC)

        # Notification type.
        if config.NOTIFICATION_TYPE == "windows_toast":
            self._radio_toast.setChecked(True)
        else:
            self._radio_popup.setChecked(True)

    # ── Signals ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._btn_save.clicked.connect(self._on_save)
        self._btn_check_update.clicked.connect(self._on_check_update)

    def _on_check_update(self) -> None:
        import webbrowser
        from updater.check_update import check_for_update

        self._btn_check_update.setEnabled(False)
        self._update_status_lbl.setText("Проверка наличия обновлений…")
        self._update_status_lbl.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        QApplication.processEvents()

        has_update, version, url = check_for_update()
        self._btn_check_update.setEnabled(True)

        if has_update:
            self._update_status_lbl.setText(
                f"🚀 Доступна новая версия {version}! "
                f'<a href="{url}" style="color:#5b8def; font-weight:600;">Скачать обновление →</a>'
            )
            self._update_status_lbl.setStyleSheet(self._css("color: #66cc99; font-size: 9.5pt;"))
            self._update_status_lbl.setOpenExternalLinks(True)
        else:
            current = getattr(config, "APP_VERSION", "1.0.0")
            self._update_status_lbl.setText(f"✓ У вас установлена актуальная версия (v{current}).")
            self._update_status_lbl.setStyleSheet(self._css("color: #8888aa; font-size: 9pt;"))

    # ── Save ─────────────────────────────────────────────

    def _on_save(self) -> None:
        key_text = self._key_input.text().strip()
        provider = "openrouter" if self._radio_or.isChecked() else "anthropic"

        # ── Update API key (if a new one was entered) ────
        if key_text:
            self._btn_save.setEnabled(False)
            self._key_status.setText("Проверяем ключ…")
            self._key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
            QApplication.processEvents()

            settings.set_api_key(provider, key_text)
            reset_client()

            from translate.llm_client import translate
            try:
                result = translate("Hello", target_lang="ru")
                if not result:
                    raise RuntimeError("Пустой ответ от API")
            except Exception as e:
                settings.delete_api_key(provider)
                reset_client()
                self._key_status.setText(f"Ошибка: {e}")
                self._key_status.setStyleSheet(self._css("color: #ff6b6b; font-size: 9pt;"))
                self._btn_save.setEnabled(True)
                return

            self._key_status.setText(f"✓ Ключ {provider} обновлён!")
            self._key_status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
            self._key_input.clear()
            self._btn_save.setEnabled(True)

        # ── Update config_manager values ─────────────────
        try:
            primary_choice = "openrouter" if self._radio_or.isChecked() else "anthropic"
            settings.save_primary_provider(primary_choice)
            settings.set_fallback_enabled(self._chk_fallback.isChecked())

            new_domain = self._domain_combo.currentData()
            new_src_lang = self._src_lang_combo.currentData()
            new_lang = self._lang_combo.currentData()
            new_engine = self._engine_combo.currentData()
            # LLM model
            combo_data = self._model_combo.currentData()
            if combo_data == "__custom__":
                new_model = self._custom_model_edit.text().strip() or "openai/gpt-oss-20b:free"
            else:
                new_model = combo_data or "openai/gpt-oss-20b:free"
            new_timeout = self._timeout_spin.value()

            from translate.backend import BACKEND_API, BACKEND_NLLB

            new_backend = self._backend_combo.currentData() or BACKEND_API
            new_nllb_path = self._nllb_path_edit.text().strip()
            backend_switched_to_nllb = (
                new_backend == BACKEND_NLLB
                and getattr(config, "TRANSLATION_BACKEND", BACKEND_API) != BACKEND_NLLB
            )

            cfg = config_manager.load_config()
            cfg["translation_backend"] = new_backend
            cfg["nllb_model_path"] = new_nllb_path
            cfg["azure_region"] = self._azure_region_input.text().strip() or "global"
            cfg["ocr_gpu_mode"] = self._ocr_gpu_combo.currentData() or "auto"
            cfg["primary_provider"] = primary_choice
            cfg["enable_fallback"] = self._chk_fallback.isChecked()
            cfg["enable_streaming"] = self._chk_streaming.isChecked()
            cfg["compact_prompt"] = self._chk_compact_prompt.isChecked()
            cfg["enable_ocr_preview"] = self._chk_ocr_preview.isChecked()
            cfg["llm_max_tokens"] = self._tokens_spin.value()
            cfg["active_domain"] = new_domain or cfg.get("active_domain", "general")
            cfg["source_language"] = new_src_lang or cfg.get("source_language", "auto")
            cfg["target_language"] = new_lang or cfg["target_language"]
            cfg["translation_engine"] = new_engine or cfg["translation_engine"]
            if new_model:
                cfg["llm_model"] = new_model
            cfg["popup_timeout_sec"] = new_timeout
            cfg["notification_type"] = "windows_toast" if self._radio_toast.isChecked() else "popup"
            config_manager.save_config(cfg)

            # Reset both backends so the new model/provider/path is picked up.
            from translate.backend import reset as reset_backends
            reset_backends()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить настройки:\n{e}"
            )
            return

        # Freshly switched to the local model → warm it up with a visible indicator
        # instead of making the user wait on their first hotkey press.
        if backend_switched_to_nllb:
            self._on_load_nllb_clicked()
        else:
            self._refresh_nllb_status()

        self.settings_saved.emit()


class SettingsDialog(QDialog):
    """Non-modal settings dialog with dark theme."""

    _WIDTH = 520

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Translator Overlay — Настройки")
        self.setFixedWidth(self._WIDTH)
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Title ──
        title = QLabel("⚙️ Настройки")
        title.setStyleSheet(SettingsWidget._css("color: #e8e8e8; font-size: 14pt; font-weight: 600;"))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # ── Settings widget ──
        self.settings_widget = SettingsWidget(self)
        self.settings_widget.settings_saved.connect(self.accept)
        layout.addWidget(self.settings_widget)

        # ── Close button row ──
        btn_row = QHBoxLayout()
        self._btn_close = QPushButton("Закрыть")
        self._btn_close.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #999; border: 1px solid #444;"
            "  border-radius: 6px; padding: 9px 24px;"
            "  font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )
        self._btn_close.clicked.connect(self.close)

        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

        root.addWidget(self._card)

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
