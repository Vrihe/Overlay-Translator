"""
ui/settings_dialog.py — runtime settings widget and dialog.

Provides:
  • SettingsWidget: reusable QWidget containing all settings controls.
  • SettingsDialog: non-modal QDialog wrapper for SettingsWidget.

Allows the user to:
  • Change the API key (with live validation)
  • Select the source and target translation language
  • Select the translation engine (llm_text / llm_vision / api)
  • Set the LLM model identifier
  • Adjust the result-popup auto-close timeout
  • Choose notification display type (popup / windows toast)
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QSpinBox, QWidget, QApplication, QGroupBox, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath, QColor

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
        "QComboBox::drop-down {"
        "  border: none; padding-right: 8px;"
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

        # ── API Key section ──
        grp_key = QGroupBox("API-ключ")
        grp_key.setStyleSheet(self._GROUP_CSS)
        key_layout = QVBoxLayout(grp_key)
        key_layout.setSpacing(8)

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

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("Новый ключ (оставьте пустым, чтобы не менять)")
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

        # LLM model
        model_row = QHBoxLayout()
        lbl_model = QLabel("LLM-модель:")
        lbl_model.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("e.g. openai/gpt-oss-20b:free")
        self._model_input.setStyleSheet(self._INPUT_CSS)
        model_row.addWidget(lbl_model)
        model_row.addWidget(self._model_input, 1)
        trans_layout.addLayout(model_row)

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

    # ── Load current values ──────────────────────────────

    def _load_current(self) -> None:
        # Provider radio + status.
        if settings.get_api_key("openrouter"):
            self._radio_or.setChecked(True)
            self._key_status.setText("✓ Ключ OpenRouter сохранён")
            self._key_status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
        elif settings.get_api_key("anthropic"):
            self._radio_ant.setChecked(True)
            self._key_status.setText("✓ Ключ Anthropic сохранён")
            self._key_status.setStyleSheet(self._css("color: #66cc99; font-size: 9pt;"))
        else:
            self._radio_or.setChecked(True)
            self._key_status.setText("Ключ не задан (используется .env)")
            self._key_status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))

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

        # LLM model.
        self._model_input.setText(config.LLM_MODEL)

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
            new_src_lang = self._src_lang_combo.currentData()
            new_lang = self._lang_combo.currentData()
            new_engine = self._engine_combo.currentData()
            new_model = self._model_input.text().strip()
            new_timeout = self._timeout_spin.value()

            cfg = config_manager.load_config()
            cfg["source_language"] = new_src_lang or cfg.get("source_language", "auto")
            cfg["target_language"] = new_lang or cfg["target_language"]
            cfg["translation_engine"] = new_engine or cfg["translation_engine"]
            if new_model:
                cfg["llm_model"] = new_model
            cfg["popup_timeout_sec"] = new_timeout
            cfg["notification_type"] = "windows_toast" if self._radio_toast.isChecked() else "popup"
            config_manager.save_config(cfg)

            # Reset the LLM client so new model is picked up.
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

    _WIDTH = 500

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
