"""
ui/settings_dialog.py — runtime settings widget and dialog.

Provides:
  • SettingsWidget: reusable QWidget containing all settings controls.
  • ProfileEditorDialog: modal QDialog for creating and editing custom domain profiles.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QSpinBox, QWidget, QApplication, QGroupBox, QMessageBox,
    QTextEdit, QScrollArea, QFrame, QListWidget, QListWidgetItem, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

import html
from typing import Any
import config
import settings
from settings import config_manager
from translate.llm_client import reset_client
from i18n import N_, UI_LANGUAGES, tr
from ui import icons, theme
from ui.hud_widgets import Chip, FieldLabel, Segmented, SwitchRow

_SOURCE_LANGUAGES = [
    ("auto", N_("Автоопределение")),
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

_UI_THEMES = [
    ("amber",   N_("Янтарь")),
    ("cyan",    N_("Циан")),
    ("crimson", N_("Малиновый")),
]

_ENGINES = [
    ("llm_text",   N_("OCR → LLM (текстовый)")),
    ("llm_vision", N_("LLM Vision (картинка)")),
    ("api",        "OCR → Google/DeepL API"),
]

# B1: Preset list of OpenRouter models requested by user.
# (model_id, display_name) — model_id is used as QComboBox itemData.
_OPENROUTER_MODELS: list[tuple[str, str]] = [
    ("openai/gpt-oss-20b:free",      "GPT OSS 20B (free)"),
    ("google/gemma-4-31b-it:free",  "Google Gemma 4 31B (free)"),
    ("poolside/laguna-s-2.1:free",  "Poolside Laguna S 2.1 (free)"),
    ("__custom__",                  N_("Другая модель...")),
]

# B3: Short hints shown below the model combo for preset models.
_MODEL_HINTS: dict[str, str] = {
    "openai/gpt-oss-20b:free":      N_("✶ Бесплатно · Базовая открытая модель"),
    "google/gemma-4-31b-it:free":  N_("✶ Бесплатно · Новая мощная открытая модель Google"),
    "poolside/laguna-s-2.1:free":  N_("✶ Бесплатно · Быстрая компактная модель для перевода"),
    "__custom__":                  N_("Впишите точный ID модели с сайта openrouter.ai"),
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

        p = theme.current()
        self.src_input = QLineEdit(source)
        self.src_input.setPlaceholderText(tr("Оригинал (напр. HP)"))
        self.src_input.setStyleSheet(theme.input_css(9.5, "5px 8px"))

        lbl_arrow = QLabel()
        lbl_arrow.setPixmap(icons.pixmap("arrow_right", p.muted, 14))
        lbl_arrow.setStyleSheet("background: transparent;")

        self.trans_input = QLineEdit(translation)
        self.trans_input.setPlaceholderText(tr("Перевод (напр. ОЗ)"))
        self.trans_input.setStyleSheet(theme.input_css(9.5, "5px 8px"))

        self.btn_delete = QPushButton()
        self.btn_delete.setIcon(icons.icon("close", p.error, 12))
        self.btn_delete.setToolTip(tr("Удалить"))
        self.btn_delete.setFixedSize(26, 26)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setStyleSheet(theme.btn_icon(danger=True))
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

        title_str = tr("Редактирование профиля") if self._existing_id else tr("Создание профиля контекста")
        self.setWindowTitle(f"Translator Overlay — {title_str}")
        self.resize(520, 520)
        self.setMinimumSize(420, 420)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setStyleSheet(f"QDialog {{ background: {theme.current().panel}; }}")

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Title
        title_text = tr("Редактирование профиля") if self._existing_id else tr("Новый профиль контекста")
        lbl_title = QLabel(title_text.upper())
        lbl_title.setFont(theme.display_font(13))
        lbl_title.setStyleSheet(f"color: {theme.current().text}; background: transparent;")
        layout.addWidget(lbl_title)

        # Display name
        layout.addWidget(FieldLabel(tr("Название профиля (display_name):").rstrip(":")))

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText(tr("Например: Фэнтези РПГ, Медицина, Юриспруденция..."))
        self._name_input.setStyleSheet(theme.input_css(10, "7px 10px"))
        layout.addWidget(self._name_input)

        # System prompt
        layout.addWidget(FieldLabel(tr("Инструкция для ИИ (system_prompt):").rstrip(":")))

        self._prompt_input = QTextEdit()
        self._prompt_input.setPlaceholderText(tr(
            "Опишите роль ИИ и правила перевода терминов, напр.:\n"
            "Ты опытный переводчик фэнтези игр. Переводи игровые термины (HP -> ОЗ, Mana -> Мана). "
            "Сохраняй геймерский сленг и атмосферу."
        ))
        self._prompt_input.setStyleSheet(theme.input_css(9.5, "8px 10px"))
        self._prompt_input.setFixedHeight(120)
        layout.addWidget(self._prompt_input)

        # Few-Shot examples header row
        ex_header = QHBoxLayout()
        ex_header.addWidget(FieldLabel(tr("Примеры перевода (Few-Shot Examples):").rstrip(":")))
        ex_header.addStretch()

        self._btn_add_ex = QPushButton(tr("+ Добавить пример"))
        self._btn_add_ex.setCursor(Qt.PointingHandCursor)
        self._btn_add_ex.setStyleSheet(theme.btn_accent("4px 10px", 8.5))
        self._btn_add_ex.clicked.connect(self._add_example_row)
        ex_header.addWidget(self._btn_add_ex)
        layout.addLayout(ex_header)

        # Scroll area for examples
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._examples_container = QWidget()
        self._examples_container.setObjectName("examplesContainer")
        self._examples_container.setStyleSheet("#examplesContainer { background: transparent; }")
        self._examples_layout = QVBoxLayout(self._examples_container)
        self._examples_layout.setContentsMargins(0, 0, 0, 0)
        self._examples_layout.setSpacing(6)
        self._examples_layout.addStretch()

        scroll.setWidget(self._examples_container)
        layout.addWidget(scroll, 1)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_cancel = QPushButton(tr("Отмена"))
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(theme.btn_secondary())
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_save = QPushButton(tr("Сохранить профиль").upper())
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setFont(theme.display_font(9.5, spacing=110))
        self._btn_save.setStyleSheet(theme.btn_primary("8px 20px", 9.5))
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
            QMessageBox.warning(self, tr("Ошибка ввода"), tr("Введите название профиля."))
            return
        if not prompt:
            QMessageBox.warning(self, tr("Ошибка ввода"), tr("Заполните системный промпт для ИИ."))
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
            QMessageBox.critical(
                self, tr("Ошибка сохранения"), tr("Не удалось сохранить профиль:\n{error}", error=e)
            )


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
        return f"font-family: '{theme.body_family()}'; background: transparent; {extra}"

    @staticmethod
    def _status_css(kind: str = "muted") -> str:
        """Status line colour by role: muted | ok | error | warn | accent."""
        return theme.text_css(getattr(theme.current(), kind), 9)

    _INPUT_CSS = ""   # set in _build_ui from ui/theme.py (needs the loaded fonts)
    _GROUP_CSS = ""

    # Settings sections: (title, page key). Group boxes are placed on the pages in
    # _build_ui; their widgets and the _load_current / _on_save logic are unchanged.
    _SECTIONS = (
        (N_("Перевод"), "translate"),
        (N_("Хоткеи"), "hotkeys"),
        (N_("Распознавание"), "ocr"),
        (N_("Попап"), "popup"),
        (N_("Интерфейс"), "interface"),
    )

    @staticmethod
    def _field(caption: str, widget: QWidget) -> QVBoxLayout:
        """Caps caption above a control."""
        box = QVBoxLayout()
        box.setSpacing(5)
        box.addWidget(FieldLabel(caption.rstrip(":")))
        box.addWidget(widget)
        return box

    @staticmethod
    def _field_row(caption: str, row: QHBoxLayout) -> QVBoxLayout:
        """Caps caption above a row of controls."""
        box = QVBoxLayout()
        box.setSpacing(5)
        box.addWidget(FieldLabel(caption.rstrip(":")))
        box.addLayout(row)
        return box

    def _group(self, title: str, spacing: int = 10) -> tuple[QGroupBox, QVBoxLayout]:
        grp = QGroupBox(title.upper())
        grp.setStyleSheet(self._GROUP_CSS + theme.check_css())
        lay = QVBoxLayout(grp)
        lay.setSpacing(spacing)
        return grp, lay

    def _build_pages(self) -> dict[str, QVBoxLayout]:
        """Section list + save button on the left, one scrollable page per section on the right."""
        p = theme.current()
        body = QHBoxLayout(self)
        body.setContentsMargins(24, 0, 16, 16)
        body.setSpacing(16)

        # Left column: the save button sits right under the sections, so it is
        # visible as soon as the page opens, whatever section is scrolled.
        self._side = QWidget()
        self._side.setFixedWidth(170)
        side = QVBoxLayout(self._side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(12)
        body.addWidget(self._side)

        self._section_list = QListWidget()
        self._section_list.setStyleSheet(
            theme.list_css()
            + f"QListWidget {{ background: {p.rail}; }}"
            + "QListWidget::item { padding: 10px 12px; }"
        )
        self._section_list.setFont(theme.body_font(8.5, medium=True, spacing=112))
        self._section_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.addWidget(self._section_list)

        self._btn_save = QPushButton(tr("Сохранить").upper())
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setFont(theme.display_font(10, spacing=112))
        self._btn_save.setStyleSheet(theme.btn_primary("9px 12px", 10))
        side.addWidget(self._btn_save)
        side.addStretch()

        self._section_stack = QStackedWidget()
        self._section_stack.setObjectName("settingsStack")
        self._section_stack.setStyleSheet("#settingsStack { background: transparent; }")
        body.addWidget(self._section_stack, 1)

        pages: dict[str, QVBoxLayout] = {}
        for title, key in self._SECTIONS:
            QListWidgetItem(tr(title).upper(), self._section_list)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            page = QWidget()
            page.setObjectName("settingsSection")
            page.setStyleSheet("#settingsSection { background: transparent; }")
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 8, 8)
            lay.setSpacing(14)
            scroll.setWidget(page)
            self._section_stack.addWidget(scroll)
            pages[key] = lay
        self._section_list.setFixedHeight(
            self._section_list.sizeHintForRow(0) * self._section_list.count() + 2)
        self._section_list.currentRowChanged.connect(self._section_stack.setCurrentIndex)
        self._section_list.setCurrentRow(0)
        return pages

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self) -> None:
        SettingsWidget._INPUT_CSS = theme.input_css(9.5) + theme.combo_css(9.5)
        SettingsWidget._GROUP_CSS = theme.group_css()
        p = theme.current()
        pages = self._build_pages()
        nmt_btn_css = theme.btn_accent("6px 12px", 8.5)

        # ── API Key & Provider section ──
        grp_key, key_layout = self._group(tr("API-ключ и провайдеры"))

        key_layout.addWidget(FieldLabel(tr("Основной провайдер:").rstrip(":")))
        prov_row = QHBoxLayout()
        prov_row.setSpacing(18)
        self._radio_group = QButtonGroup(self)
        self._radio_or = QRadioButton("OpenRouter")
        self._radio_ant = QRadioButton("Anthropic")
        self._radio_group.addButton(self._radio_or, 0)
        self._radio_group.addButton(self._radio_ant, 1)
        prov_row.addWidget(self._radio_or)
        prov_row.addWidget(self._radio_ant)
        prov_row.addStretch()
        key_layout.addLayout(prov_row)

        self._chk_fallback = SwitchRow(tr("Автоматически переключаться на резервный провайдер при сбое (Fallback)"))
        key_layout.addWidget(self._chk_fallback)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText(tr("Новый API-ключ для выбранного провайдера (оставьте пустым, если не меняется)"))
        self._key_input.setStyleSheet(self._INPUT_CSS)
        key_row.addWidget(self._key_input, 1)
        self._btn_check_key = QPushButton(tr("Проверить"))
        self._btn_check_key.setCursor(Qt.PointingHandCursor)
        self._btn_check_key.setStyleSheet(theme.btn_accent("7px 14px", 9))
        self._btn_check_key.clicked.connect(self._on_check_llm_key)
        key_row.addWidget(self._btn_check_key)
        key_layout.addLayout(self._field_row(tr("API-ключ"), key_row))

        self._key_status = QLabel("")
        self._key_status.setTextFormat(Qt.PlainText)  # shows provider error text
        self._key_status.setWordWrap(True)
        self._key_status.setStyleSheet(self._status_css())
        key_layout.addWidget(self._key_status)

        pages["translate"].addWidget(grp_key)

        # ── Translation backend section ──
        grp_backend, backend_layout = self._group(tr("Бэкенд перевода"))

        self._backend_seg = Segmented([(tr("Облако (API)"), "cloud"), (tr("Локально (NLLB)"), "nllb")])
        self._backend_seg.changed.connect(self._on_backend_segment)
        self._last_cloud_backend = "api"
        backend_layout.addWidget(self._backend_seg)

        # Backend combo (replaces the old pair of radio buttons).
        from translate.backend import BACKENDS as _ALL_BACKENDS
        self._backend_combo = QComboBox()
        self._backend_combo.setStyleSheet(self._INPUT_CSS)
        for bid, blabel in _ALL_BACKENDS:
            self._backend_combo.addItem(tr(blabel), bid)
        backend_layout.addLayout(self._field(tr("Чем выполнять перевод:"), self._backend_combo))

        # ── NLLB-specific widgets (hidden when another backend is active) ──
        self._nllb_container = QWidget()
        nllb_inner = QVBoxLayout(self._nllb_container)
        nllb_inner.setContentsMargins(0, 4, 0, 0)
        nllb_inner.setSpacing(8)

        # Optional explicit model path (empty = auto-discover).
        self._nllb_path_edit = QLineEdit()
        self._nllb_path_edit.setPlaceholderText(
            tr("оставьте пустым для автопоиска (…/models/nllb-200-ct2-int8)")
        )
        self._nllb_path_edit.setStyleSheet(self._INPUT_CSS)
        nllb_inner.addLayout(self._field(tr("Путь к модели:"), self._nllb_path_edit))

        status_row = QHBoxLayout()
        self._nllb_status = QLabel("")
        self._nllb_status.setWordWrap(True)
        self._nllb_status.setStyleSheet(self._status_css())
        status_row.addWidget(self._nllb_status, 1)

        self._btn_load_nllb = QPushButton(tr("Загрузить модель"))
        self._btn_load_nllb.setCursor(Qt.PointingHandCursor)
        self._btn_load_nllb.setToolTip(tr("Проверить наличие модели и прогреть её в памяти"))
        self._btn_load_nllb.setStyleSheet(nmt_btn_css)
        self._btn_load_nllb.clicked.connect(self._on_load_nllb_clicked)
        status_row.addWidget(self._btn_load_nllb, 0, Qt.AlignTop)
        nllb_inner.addLayout(status_row)

        backend_layout.addWidget(self._nllb_container)

        self._backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        pages["translate"].addWidget(grp_backend)

        # ── NMT API keys section ──
        grp_nmt, nmt_layout = self._group(tr("Ключи быстрых переводчиков"))

        def _key_block(title: str, hint: str, placeholder: str, provider: str):
            nmt_layout.addWidget(FieldLabel(title))
            if hint:
                lbl_hint = QLabel(hint)
                lbl_hint.setWordWrap(True)
                lbl_hint.setStyleSheet(theme.label_css("caption"))
                nmt_layout.addWidget(lbl_hint)
            row = QHBoxLayout()
            row.setSpacing(8)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setEchoMode(QLineEdit.Password)
            edit.setStyleSheet(self._INPUT_CSS)
            row.addWidget(edit, 1)
            btn_save = QPushButton(tr("Сохранить"))
            btn_save.setStyleSheet(nmt_btn_css)
            btn_save.setCursor(Qt.PointingHandCursor)
            btn_save.clicked.connect(lambda: self._save_nmt_key(provider))
            row.addWidget(btn_save)
            btn_test = QPushButton(tr("Проверить"))
            btn_test.setStyleSheet(nmt_btn_css)
            btn_test.setCursor(Qt.PointingHandCursor)
            btn_test.clicked.connect(lambda: self._test_nmt_key(provider))
            row.addWidget(btn_test)
            nmt_layout.addLayout(row)
            return edit, btn_save, btn_test

        # ── Google API Key ──
        (self._google_key_input, self._btn_save_google, self._btn_test_google) = _key_block(
            "Google API Key", tr("Необязательно — без ключа работает через бесплатный Web RPC"),
            "AIza...", "google")
        self._google_key_status = QLabel("")
        self._google_key_status.setWordWrap(True)
        self._google_key_status.setStyleSheet(self._status_css())
        nmt_layout.addWidget(self._google_key_status)

        # ── DeepL API Key ──
        (self._deepl_key_input, self._btn_save_deepl, self._btn_test_deepl) = _key_block(
            "DeepL API Key", tr("Free или Pro ключ (суффикс :fx = Free)"),
            "xxxxxxxx-xxxx-...:fx", "deepl")
        self._deepl_key_status = QLabel("")
        self._deepl_key_status.setWordWrap(True)
        self._deepl_key_status.setStyleSheet(self._status_css())
        nmt_layout.addWidget(self._deepl_key_status)

        # ── Azure Translator Key + Region ──
        (self._azure_key_input, self._btn_save_azure, self._btn_test_azure) = _key_block(
            "Azure Translator Key", "", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "azure")
        self._azure_region_input = QLineEdit()
        self._azure_region_input.setPlaceholderText("global")
        self._azure_region_input.setStyleSheet(self._INPUT_CSS)
        nmt_layout.addLayout(self._field(tr("Регион:"), self._azure_region_input))

        self._azure_key_status = QLabel("")
        self._azure_key_status.setWordWrap(True)
        self._azure_key_status.setStyleSheet(self._status_css())
        nmt_layout.addWidget(self._azure_key_status)

        pages["translate"].addWidget(grp_nmt)

        # ── OCR GPU acceleration ──
        grp_ocr_gpu, ocr_gpu_layout = self._group(tr("Ускорение OCR (видеокарта)"))

        # GPU info label
        gpu_info = self._detect_gpu_info()
        self._gpu_info_label = QLabel(gpu_info)
        self._gpu_info_label.setWordWrap(True)
        self._gpu_info_label.setStyleSheet(self._status_css())
        ocr_gpu_layout.addWidget(self._gpu_info_label)

        # A legacy "gpu" value behaves like "auto" and shows as the first item.
        self._ocr_gpu_combo = QComboBox()
        self._ocr_gpu_combo.setStyleSheet(self._INPUT_CSS)
        self._ocr_gpu_combo.addItem(tr("Авто (видеокарта через DirectML, если доступна)"), "auto")
        self._ocr_gpu_combo.addItem(tr("Только процессор (CPU)"), "cpu")
        ocr_gpu_layout.addLayout(self._field(tr("Режим OCR:"), self._ocr_gpu_combo))

        # D1: OCR preview switch
        self._chk_ocr_preview = SwitchRow(tr("Предпросмотр и правка OCR-текста перед переводом"))
        ocr_gpu_layout.addWidget(self._chk_ocr_preview)

        pages["ocr"].addWidget(grp_ocr_gpu)

        # ── Translation section ──
        grp_trans, trans_layout = self._group(tr("Перевод"))

        # Context / Domain
        self._domain_combo = QComboBox()
        self._domain_combo.setStyleSheet(self._INPUT_CSS)
        from translate.domain_manager import list_available_domains
        for d in list_available_domains():
            self._domain_combo.addItem(f"{d['display_name']} ({d['id']})", d["id"])
        trans_layout.addLayout(self._field(tr("Контекст перевода:"), self._domain_combo))

        # Source / target language in two columns
        self._src_lang_combo = QComboBox()
        self._src_lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _SOURCE_LANGUAGES:
            self._src_lang_combo.addItem(f"{tr(name)} ({code})", code)

        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _TARGET_LANGUAGES:
            self._lang_combo.addItem(f"{name} ({code})", code)

        lang_cols = QHBoxLayout()
        lang_cols.setSpacing(12)
        lang_cols.addLayout(self._field(tr("Исходный язык:"), self._src_lang_combo), 1)
        lang_cols.addLayout(self._field(tr("Язык перевода:"), self._lang_combo), 1)
        trans_layout.addLayout(lang_cols)

        # Switch on = source "auto" (the combo is the saved value; the switch only drives it).
        self._sw_auto_lang = SwitchRow(tr("Автоопределение исходного языка"))
        self._sw_auto_lang.toggled.connect(self._on_auto_lang_toggled)
        self._src_lang_combo.currentIndexChanged.connect(self._sync_auto_lang_switch)
        trans_layout.addWidget(self._sw_auto_lang)

        # Translation engine
        self._engine_combo = QComboBox()
        self._engine_combo.setStyleSheet(self._INPUT_CSS)
        for eng_id, eng_label in _ENGINES:
            self._engine_combo.addItem(tr(eng_label), eng_id)
        trans_layout.addLayout(self._field(tr("Движок перевода:"), self._engine_combo))

        # LLM model — Standard clean dropdown matching other settings + custom model field
        self._model_combo = QComboBox()
        self._model_combo.setEditable(False)
        self._model_combo.setMaxVisibleItems(10)
        self._model_combo.setStyleSheet(self._INPUT_CSS)
        self._populate_model_combo()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        trans_layout.addLayout(self._field(tr("LLM-модель:"), self._model_combo))

        # Custom model input (visible only when "Другая модель..." is selected)
        self._custom_model_row_widget = QWidget()
        custom_row_layout = QVBoxLayout(self._custom_model_row_widget)
        custom_row_layout.setContentsMargins(0, 2, 0, 2)
        self._custom_model_edit = QLineEdit()
        self._custom_model_edit.setPlaceholderText(tr("например: meta-llama/llama-3.3-70b-instruct"))
        self._custom_model_edit.setStyleSheet(self._INPUT_CSS)
        custom_row_layout.addLayout(self._field(tr("ID модели:"), self._custom_model_edit))
        self._custom_model_row_widget.setVisible(False)
        trans_layout.addWidget(self._custom_model_row_widget)

        # B3: hint label
        self._model_hint = QLabel("")
        self._model_hint.setStyleSheet(theme.text_css(p.muted, 8.5, italic=True))
        self._model_hint.setWordWrap(True)
        trans_layout.addWidget(self._model_hint)

        # Streaming switch
        self._chk_streaming = SwitchRow(tr("Потоковый вывод перевода (Streaming)"))
        self._chk_streaming.setToolTip(tr("Выводить перевод слово за словом сразу по мере генерации ответа моделью"))
        trans_layout.addWidget(self._chk_streaming)

        # Compact prompt switch
        self._chk_compact_prompt = SwitchRow(tr("Компактный системный промпт (ускорение отклика)"))
        self._chk_compact_prompt.setToolTip(tr("Сокращает служебные инструкции запроса, ускоряя начало ответа модели на ~30–50%"))
        trans_layout.addWidget(self._chk_compact_prompt)

        # Max tokens row
        self._tokens_spin = QSpinBox()
        self._tokens_spin.setRange(50, 2000)
        self._tokens_spin.setSingleStep(50)
        self._tokens_spin.setSuffix(tr(" токенов"))
        self._tokens_spin.setStyleSheet(self._INPUT_CSS)
        trans_layout.addLayout(self._field(tr("Макс. токенов ответа:"), self._tokens_spin))

        pages["translate"].addWidget(grp_trans)

        # ── Custom Profiles section ("Мои профили") ──
        grp_custom, custom_layout = self._group(tr("Мои профили контекста"), spacing=8)

        c_head = QHBoxLayout()
        lbl_c_desc = QLabel(tr("Кастомные промпты и словари для адаптивного перевода:"))
        lbl_c_desc.setWordWrap(True)
        lbl_c_desc.setStyleSheet(self._status_css())
        c_head.addWidget(lbl_c_desc, 1)

        self._btn_create_profile = QPushButton(tr("+ Новый профиль"))
        self._btn_create_profile.setCursor(Qt.PointingHandCursor)
        self._btn_create_profile.setStyleSheet(nmt_btn_css)
        self._btn_create_profile.clicked.connect(self._on_create_profile)
        c_head.addWidget(self._btn_create_profile, 0, Qt.AlignTop)
        custom_layout.addLayout(c_head)

        self._custom_profiles_container = QWidget()
        self._custom_profiles_layout = QVBoxLayout(self._custom_profiles_container)
        self._custom_profiles_layout.setContentsMargins(0, 4, 0, 0)
        self._custom_profiles_layout.setSpacing(6)
        custom_layout.addWidget(self._custom_profiles_container)

        pages["translate"].addWidget(grp_custom)

        # ── Hotkeys section (read-only overview) ──
        grp_hotkeys, hotkeys_layout = self._group(tr("Хоткеи"))
        self._hotkey_chip = Chip(kind="accent")
        self._settings_hotkey_chip = Chip(kind="neutral")
        for caption, chip in ((tr("Перевод области"), self._hotkey_chip),
                              (tr("Окно настроек"), self._settings_hotkey_chip)):
            row = QHBoxLayout()
            row.addWidget(FieldLabel(caption))
            row.addStretch()
            row.addWidget(chip)
            hotkeys_layout.addLayout(row)
        lbl_hk_hint = QLabel(tr("Бинды для пресетов областей назначаются в меню трея → «Пресеты регионов»."))
        lbl_hk_hint.setWordWrap(True)
        lbl_hk_hint.setStyleSheet(theme.label_css("caption"))
        hotkeys_layout.addWidget(lbl_hk_hint)
        pages["hotkeys"].addWidget(grp_hotkeys)

        # ── Interface section ──
        grp_ui, ui_layout = self._group(tr("Интерфейс"))

        self._ui_lang_combo = QComboBox()
        self._ui_lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in UI_LANGUAGES:
            self._ui_lang_combo.addItem(name, code)

        self._theme_combo = QComboBox()
        self._theme_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _UI_THEMES:
            self._theme_combo.addItem(tr(name), code)

        ui_cols = QHBoxLayout()
        ui_cols.setSpacing(12)
        ui_cols.addLayout(self._field(tr("Язык интерфейса:"), self._ui_lang_combo), 1)
        ui_cols.addLayout(self._field(tr("Цветовая схема"), self._theme_combo), 1)
        ui_layout.addLayout(ui_cols)

        lbl_ui_lang_hint = QLabel(tr("Язык и цветовая схема применяются после перезапуска приложения."))
        lbl_ui_lang_hint.setWordWrap(True)
        lbl_ui_lang_hint.setStyleSheet(theme.text_css(p.muted, 8.5, italic=True))
        ui_layout.addWidget(lbl_ui_lang_hint)

        pages["interface"].addWidget(grp_ui)

        # ── Notifications section ──
        grp_notify, notify_layout = self._group(tr("Уведомления"), spacing=8)

        self._radio_notify_group = QButtonGroup(self)
        self._radio_popup = QRadioButton(tr("Показывать результат в попап-окне"))
        self._radio_toast = QRadioButton(tr("Показывать через системные уведомления Windows"))
        self._radio_notify_group.addButton(self._radio_popup, 0)
        self._radio_notify_group.addButton(self._radio_toast, 1)
        notify_layout.addWidget(self._radio_popup)
        notify_layout.addWidget(self._radio_toast)

        # Popup timeout
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(3, 60)
        self._timeout_spin.setSuffix(tr(" сек"))
        self._timeout_spin.setStyleSheet(self._INPUT_CSS)
        notify_layout.addSpacing(4)
        notify_layout.addLayout(self._field(tr("Автоскрытие попапа (сек):"), self._timeout_spin))

        # Popup size: set by dragging the popup's edges, remembered across launches.
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        self._popup_size_lbl = QLabel("")
        self._popup_size_lbl.setWordWrap(True)
        self._popup_size_lbl.setStyleSheet(self._status_css())
        size_row.addWidget(self._popup_size_lbl, 1)
        self._btn_reset_popup_size = QPushButton(tr("Сбросить размер"))
        self._btn_reset_popup_size.setCursor(Qt.PointingHandCursor)
        self._btn_reset_popup_size.setStyleSheet(theme.btn_secondary("6px 12px", 8.5))
        self._btn_reset_popup_size.clicked.connect(self._on_reset_popup_size)
        size_row.addWidget(self._btn_reset_popup_size, 0, Qt.AlignTop)
        notify_layout.addLayout(self._field_row(tr("Размер попапа"), size_row))

        pages["popup"].addWidget(grp_notify)

        # ── About & Updates section ──
        grp_about, about_layout = self._group(tr("О программе и обновления"), spacing=8)

        ver_row = QHBoxLayout()
        self._lbl_ver = QLabel(
            tr("Версия приложения: v{version}", version=getattr(config, "APP_VERSION", "1.0.0"))
        )
        self._lbl_ver.setStyleSheet(theme.text_css(p.text, 9.5))
        ver_row.addWidget(self._lbl_ver)
        ver_row.addStretch()

        self._btn_check_update = QPushButton(tr("Проверить обновления"))
        self._btn_check_update.setCursor(Qt.PointingHandCursor)
        self._btn_check_update.setStyleSheet(nmt_btn_css)
        ver_row.addWidget(self._btn_check_update)
        about_layout.addLayout(ver_row)

        self._update_status_lbl = QLabel("")
        self._update_status_lbl.setWordWrap(True)
        self._update_status_lbl.setStyleSheet(self._status_css())
        about_layout.addWidget(self._update_status_lbl)

        pages["interface"].addWidget(grp_about)

        for lay in pages.values():
            lay.addStretch()

        # Long item texts must not set the page's minimum width (narrow windows).
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)

    def resizeEvent(self, event):
        # Narrow windows: give the section pages the room the section list takes.
        self._side.setFixedWidth(150 if event.size().width() < 700 else 170)
        super().resizeEvent(event)

    # ── Popup size ───────────────────────────────────────

    def _refresh_popup_size(self) -> None:
        from ui.result_popup import ResultPopup
        size = ResultPopup.saved_size()
        if size is None:
            self._popup_size_lbl.setText(tr("Подстраивается под текст. Растяните попап за край, чтобы задать свой размер."))
        else:
            self._popup_size_lbl.setText(tr("Сохранён: {width} × {height}", width=size.width(), height=size.height()))
        self._btn_reset_popup_size.setEnabled(size is not None)

    def _on_reset_popup_size(self) -> None:
        config.POPUP_SIZE = None
        self._refresh_popup_size()

    # ── Backend segment / auto language / key check ─────

    def _on_backend_segment(self, choice) -> None:
        """The "cloud / local" segmented control drives the backend combo."""
        from translate.backend import BACKEND_NLLB
        on_nllb = self._backend_combo.currentData() == BACKEND_NLLB
        if (choice == "nllb") == on_nllb:
            return
        target = BACKEND_NLLB if choice == "nllb" else self._last_cloud_backend
        idx = self._backend_combo.findData(target)
        if idx >= 0:
            self._backend_combo.setCurrentIndex(idx)

    def _sync_backend_segment(self) -> None:
        from translate.backend import BACKEND_NLLB
        current = self._backend_combo.currentData()
        if current and current != BACKEND_NLLB:
            self._last_cloud_backend = current
        self._backend_seg.set_current("nllb" if current == BACKEND_NLLB else "cloud")

    def _sync_auto_lang_switch(self, _index=None) -> None:
        is_auto = self._src_lang_combo.currentData() == "auto"
        self._sw_auto_lang.blockSignals(True)
        self._sw_auto_lang.setChecked(is_auto)
        self._sw_auto_lang.blockSignals(False)
        self._src_lang_combo.setEnabled(not is_auto)

    def _on_auto_lang_toggled(self, on: bool) -> None:
        if on:
            idx = self._src_lang_combo.findData("auto")
        elif self._src_lang_combo.currentData() == "auto":
            idx = self._src_lang_combo.findData("en")
        else:
            idx = self._src_lang_combo.currentIndex()
        if idx >= 0:
            self._src_lang_combo.setCurrentIndex(idx)
        self._sync_auto_lang_switch()

    def _on_check_llm_key(self) -> None:
        """Validate the typed LLM key with its provider without saving it."""
        key_text = self._key_input.text().strip()
        if not key_text:
            self._key_status.setText(tr("Введите ключ."))
            self._key_status.setStyleSheet(self._status_css("error"))
            return
        provider = "openrouter" if self._radio_or.isChecked() else "anthropic"
        self._btn_check_key.setEnabled(False)
        self._key_status.setText(tr("Проверяем ключ…"))
        self._key_status.setStyleSheet(self._status_css())
        QApplication.processEvents()
        from translate.llm_client import validate_api_key
        try:
            validate_api_key(provider, key_text)
        except Exception as e:
            self._key_status.setText(tr("Ошибка: {error}", error=e))
            self._key_status.setStyleSheet(self._status_css("error"))
        else:
            self._key_status.setText(tr("✓ Ключ {provider} работает. Нажмите «Сохранить».", provider=provider))
            self._key_status.setStyleSheet(self._status_css("ok"))
        finally:
            self._btn_check_key.setEnabled(True)

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
            empty_lbl = QLabel(tr("У вас пока нет пользовательских профилей."))
            empty_lbl.setStyleSheet(theme.text_css(theme.current().muted, 9, italic=True))
            self._custom_profiles_layout.addWidget(empty_lbl)
            return

        for dom in custom_domains:
            dom_id = dom["id"]
            display_name = dom["display_name"]

            p = theme.current()
            row = QFrame()
            row.setObjectName("profileRow")
            row.setStyleSheet(theme.panel_css("profileRow", background=p.bg))
            r_layout = QHBoxLayout(row)
            r_layout.setContentsMargins(10, 6, 8, 6)

            lbl = QLabel(
                f"{html.escape(display_name)} "
                f"<span style='color:{p.muted}; font-size:8.5pt;'>({html.escape(dom_id)})</span>"
            )
            lbl.setStyleSheet(theme.text_css(p.text, 9.5))
            r_layout.addWidget(lbl)
            r_layout.addStretch()

            btn_edit = QPushButton(tr("Редактировать"))
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.setStyleSheet(theme.btn_secondary("4px 10px", 8.5))
            btn_edit.clicked.connect(lambda _, did=dom_id: self._on_edit_profile(did))
            r_layout.addWidget(btn_edit)

            btn_del = QPushButton(tr("Удалить"))
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet(theme.btn_danger("4px 10px", 8.5))
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
            tr("Подтверждение удаления"),
            tr(
                "Вы действительно хотите удалить пользовательский профиль '{name}' ({id})?",
                name=display_name, id=domain_id,
            ),
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
            self._model_combo.addItem(tr(display), model_id)
        self._model_combo.blockSignals(False)

        # Restore previously selected value
        if saved_data:
            found = self._model_combo.findData(saved_data)
            if found >= 0:
                self._model_combo.setCurrentIndex(found)

    @staticmethod
    def _detect_gpu_info() -> str:
        """Return a human-readable string about GPU support for OCR."""
        from ocr.engine import _dml_available
        if _dml_available():
            return tr("✓ DirectML доступен — OCR может работать на видеокарте")
        return tr("DirectML недоступен — OCR будет работать на CPU")

    def _on_model_changed(self, index: int) -> None:
        """Show a short hint below the combo and toggle the custom model field."""
        model_id = self._model_combo.itemData(index)
        is_custom = (model_id == "__custom__")
        if hasattr(self, "_custom_model_row_widget"):
            self._custom_model_row_widget.setVisible(is_custom)
        hint = _MODEL_HINTS.get(str(model_id), "")
        self._model_hint.setText(tr(hint) if hint else "")

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
            status.setText(tr("Введите ключ."))
            status.setStyleSheet(self._status_css("error"))
            return

        try:
            settings.set_api_key(provider, key_text)
        except Exception as e:
            status.setText(tr("Ошибка сохранения: {error}", error=e))
            status.setStyleSheet(self._status_css("error"))
            return

        # Also persist azure_region when saving azure key.
        if provider == "azure":
            region = self._azure_region_input.text().strip() or "global"
            config_manager.set_value("azure_region", region)

        status.setText(tr("✓ Ключ {provider} сохранён!", provider=provider))
        status.setStyleSheet(self._status_css("ok"))
        self._nmt_key_input(provider).clear()
        self._refresh_nmt_key_status()

    def _test_nmt_key(self, provider: str) -> None:
        """Send a test phrase through the NMT backend and show the result."""
        status = self._nmt_status_label(provider)
        status.setText(tr("Проверяем…"))
        status.setStyleSheet(self._status_css())
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
            status.setStyleSheet(self._status_css("ok"))
        except Exception as e:
            status.setText(f"✗ {e}")
            status.setStyleSheet(self._status_css("error"))

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
                label.setText(tr("✓ Ключ {provider} сохранён в Keyring", provider=name))
                label.setStyleSheet(self._status_css("ok"))
            else:
                if provider == "google":
                    label.setText(tr("Ключ не задан — будет использоваться бесплатный Web RPC"))
                else:
                    label.setText(tr("Ключ {provider} не задан", provider=name))
                label.setStyleSheet(self._status_css())

        # Azure region.
        self._azure_region_input.setText(config_manager.get("azure_region") or "global")

    # ── Load current values ──────────────────────────────

    # ── Translation backend (API / local NLLB) ──────────

    def _set_nllb_status(self, message: str, *, kind: str = "muted") -> None:
        self._nllb_status.setText(message)
        self._nllb_status.setStyleSheet(self._status_css(kind))

    def _refresh_nllb_status(self) -> None:
        """Show whether the local model is present, without loading it."""
        from translate.backend import BACKEND_NLLB
        self._sync_backend_segment()
        use_nllb = self._backend_combo.currentData() == BACKEND_NLLB
        self._nllb_container.setVisible(use_nllb)

        if not use_nllb:
            return

        from translate.nllb_backend import get_backend, resolve_model_dir

        backend = get_backend()
        if backend.is_loaded:
            self._set_nllb_status(
                tr("✓ Модель загружена в память: {path}", path=backend.model_dir), kind="ok"
            )
            return

        found = resolve_model_dir()
        if found is not None:
            self._set_nllb_status(
                tr(
                    "✓ Модель найдена: {path}\nБудет загружена при первом переводе "
                    "(или нажмите «Загрузить модель»).",
                    path=found,
                ),
                kind="ok",
            )
        else:
            self._set_nllb_status(
                tr(
                    "⚠ Локальная модель NLLB не найдена. Укажите путь к каталогу "
                    "nllb-200-ct2-int8 выше либо сконвертируйте модель "
                    "(ct2-transformers-converter). Пока модель недоступна, перевод "
                    "будет выполняться через API."
                ),
                kind="warn",
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
        self._set_nllb_status(tr("Загрузка локальной модели… (около 600 МБ, 1–5 с)"))
        QApplication.processEvents()

        self._nllb_worker = _NllbPreloadWorker(self)
        self._nllb_worker.finished_with_status.connect(self._on_nllb_preload_done)
        self._nllb_worker.start()

    def _on_nllb_preload_done(self, ok: bool, message: str) -> None:
        from translate.backend import BACKEND_NLLB
        self._btn_load_nllb.setEnabled(self._backend_combo.currentData() == BACKEND_NLLB)
        if ok:
            self._set_nllb_status(f"✓ {message}", kind="ok")
        else:
            self._set_nllb_status(
                f"⚠ {message}\n\n"
                + tr("Пока модель недоступна, перевод будет выполняться через API."),
                kind="warn",
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
            self._key_status.setText(tr("Сохранённые ключи: ") + ", ".join(status_parts))
            self._key_status.setStyleSheet(self._status_css("ok"))
        else:
            self._key_status.setText(tr("Ключи не заданы в Keyring (используются переменные из .env)"))
            self._key_status.setStyleSheet(self._status_css())

        # Domain.
        self._refresh_all_domain_combos()

        # Custom profiles list.
        self._reload_custom_profiles_list()

        # Source language.
        idx_src = self._src_lang_combo.findData(config.SOURCE_LANG)
        if idx_src >= 0:
            self._src_lang_combo.setCurrentIndex(idx_src)
        self._sync_auto_lang_switch()

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

        # Popup timeout and saved size.
        self._timeout_spin.setValue(config.POPUP_TIMEOUT_SEC)
        self._refresh_popup_size()

        # Interface language and colour scheme.
        idx_ui = self._ui_lang_combo.findData(config_manager.get("ui_language"))
        self._ui_lang_combo.setCurrentIndex(max(idx_ui, 0))
        idx_theme = self._theme_combo.findData(config_manager.get("ui_theme"))
        self._theme_combo.setCurrentIndex(max(idx_theme, 0))

        # Hotkeys overview.
        self._hotkey_chip.set_chip_text(str(config.HOTKEY or "").upper())
        self._settings_hotkey_chip.set_chip_text(str(config.SETTINGS_HOTKEY or "").upper())

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
        self._update_status_lbl.setText(tr("Проверка наличия обновлений…"))
        self._update_status_lbl.setStyleSheet(self._status_css())
        QApplication.processEvents()

        has_update, version, url = check_for_update()
        self._btn_check_update.setEnabled(True)

        if has_update:
            self._update_status_lbl.setText(
                tr("Доступна новая версия {version}. ", version=html.escape(version))
                + f'<a href="{html.escape(url)}" style="color:{theme.current().accent};">'
                + tr("Скачать обновление →") + "</a>"
            )
            self._update_status_lbl.setStyleSheet(self._status_css("ok"))
            self._update_status_lbl.setOpenExternalLinks(True)
        else:
            current = getattr(config, "APP_VERSION", "1.0.0")
            self._update_status_lbl.setText(tr("✓ У вас установлена актуальная версия (v{version}).", version=current))
            self._update_status_lbl.setStyleSheet(self._status_css())

    # ── Save ─────────────────────────────────────────────

    def _on_save(self) -> None:
        key_text = self._key_input.text().strip()
        provider = "openrouter" if self._radio_or.isChecked() else "anthropic"

        # ── Update API key (if a new one was entered) ────
        if key_text:
            self._btn_save.setEnabled(False)
            self._key_status.setText(tr("Проверяем ключ…"))
            self._key_status.setStyleSheet(self._status_css())
            QApplication.processEvents()

            # Check before storing, so a rejected key never replaces a working one.
            from translate.llm_client import validate_api_key
            try:
                validate_api_key(provider, key_text)
            except Exception as e:
                self._key_status.setText(tr("Ошибка: {error}", error=e))
                self._key_status.setStyleSheet(self._status_css("error"))
                self._btn_save.setEnabled(True)
                return

            settings.set_api_key(provider, key_text)
            reset_client()
            self._key_status.setText(tr("✓ Ключ {provider} обновлён!", provider=provider))
            self._key_status.setStyleSheet(self._status_css("ok"))
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
            new_ui_lang = self._ui_lang_combo.currentData() or "auto"
            ui_lang_changed = new_ui_lang != cfg.get("ui_language", "auto")
            cfg["ui_language"] = new_ui_lang
            new_theme = self._theme_combo.currentData() or "amber"
            theme_changed = new_theme != cfg.get("ui_theme", "amber")
            cfg["ui_theme"] = new_theme
            config_manager.save_config(cfg)

            # Reset both backends so the new model/provider/path is picked up.
            from translate.backend import reset as reset_backends
            reset_backends()
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("Ошибка сохранения"),
                tr("Не удалось сохранить настройки:\n{error}", error=e)
            )
            return

        restart_notes = []
        if ui_lang_changed:
            restart_notes.append(tr("Язык интерфейса изменится после перезапуска приложения."))
        if theme_changed:
            restart_notes.append(tr("Цветовая схема изменится после перезапуска приложения."))
        if restart_notes:
            QMessageBox.information(self, tr("Интерфейс"), "\n".join(restart_notes))

        # Freshly switched to the local model → warm it up with a visible indicator
        # instead of making the user wait on their first hotkey press.
        if backend_switched_to_nllb:
            self._on_load_nllb_clicked()
        else:
            self._refresh_nllb_status()

        self.settings_saved.emit()
