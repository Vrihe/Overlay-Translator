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
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QMetaObject, Q_ARG
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

        # D1: OCR preview checkbox
        self._chk_ocr_preview = QCheckBox("Предпросмотр и правка OCR-текста перед переводом")
        self._chk_ocr_preview.setStyleSheet(self._css("color: #ccc; font-size: 9.5pt; margin-top: 2px;"))
        trans_layout.addWidget(self._chk_ocr_preview)

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

    def _on_model_changed(self, index: int) -> None:
        """Show a short hint below the combo and toggle the custom model field."""
        model_id = self._model_combo.itemData(index)
        is_custom = (model_id == "__custom__")
        if hasattr(self, "_custom_model_row_widget"):
            self._custom_model_row_widget.setVisible(is_custom)
        hint = _MODEL_HINTS.get(str(model_id), "")
        self._model_hint.setText(hint)

    # ── Load current values ──────────────────────────────

    def _load_current(self) -> None:

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
        current_model = config.OPENROUTER_MODEL or config.LLM_MODEL or "openai/gpt-oss-20b:free"
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

        # Streaming & OCR Preview
        self._chk_streaming.setChecked(bool(getattr(config, "ENABLE_STREAMING", True)))
        self._chk_ocr_preview.setChecked(bool(getattr(config, "ENABLE_OCR_PREVIEW", False)))

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

            cfg = config_manager.load_config()
            cfg["primary_provider"] = primary_choice
            cfg["enable_fallback"] = self._chk_fallback.isChecked()
            cfg["enable_streaming"] = self._chk_streaming.isChecked()
            cfg["enable_ocr_preview"] = self._chk_ocr_preview.isChecked()
            cfg["active_domain"] = new_domain or cfg.get("active_domain", "general")
            cfg["source_language"] = new_src_lang or cfg.get("source_language", "auto")
            cfg["target_language"] = new_lang or cfg["target_language"]
            cfg["translation_engine"] = new_engine or cfg["translation_engine"]
            if new_model:
                cfg["llm_model"] = new_model
            cfg["popup_timeout_sec"] = new_timeout
            cfg["notification_type"] = "windows_toast" if self._radio_toast.isChecked() else "popup"
            config_manager.save_config(cfg)

            # Reset the LLM client so new model/provider is picked up.
            reset_client()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить настройки:\n{e}"
            )
            return

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
