"""
ui/settings_dialog.py — runtime settings dialog.

Opened via Ctrl+Shift+O (or the tray menu).  Allows the user to:
  • Change the API key (with live validation)
  • Select the target translation language
  • Adjust the result-popup auto-close timeout
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QComboBox,
    QSpinBox, QWidget, QApplication, QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPainterPath, QColor

import config
import settings
from translate.llm_client import reset_client

# ── Supported target languages ───────────────────────────

_LANGUAGES = [
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
        self._load_current()
        self._connect_signals()

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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Title ──
        title = QLabel("⚙️ Настройки")
        title.setStyleSheet(self._css("color: #e8e8e8; font-size: 14pt; font-weight: 600;"))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # ── API Key section ──
        grp_key = QGroupBox("API-ключ")
        grp_key.setStyleSheet(self._GROUP_CSS)
        key_layout = QVBoxLayout(grp_key)
        key_layout.setSpacing(8)

        # Provider radio
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

        # Key input
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("Новый ключ (оставьте пустым, чтобы не менять)")
        self._key_input.setStyleSheet(self._INPUT_CSS)
        key_layout.addWidget(self._key_input)

        # Key status
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

        # Target language
        lang_row = QHBoxLayout()
        lbl_lang = QLabel("Язык перевода:")
        lbl_lang.setStyleSheet(self._css("color: #ccc; font-size: 10pt;"))
        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet(self._INPUT_CSS)
        for code, name in _LANGUAGES:
            self._lang_combo.addItem(f"{name} ({code})", code)
        lang_row.addWidget(lbl_lang)
        lang_row.addWidget(self._lang_combo, 1)
        trans_layout.addLayout(lang_row)

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
        self._btn_close = QPushButton("Закрыть")
        self._btn_close.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #999; border: 1px solid #444;"
            "  border-radius: 6px; padding: 9px 24px;"
            "  font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )

        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

        root.addWidget(self._card)

    # ── Load current values ──────────────────────────────

    def _load_current(self) -> None:
        # Select the provider that currently has a key.
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

        # Target language combo.
        idx = self._lang_combo.findData(config.TARGET_LANG)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        # Popup timeout.
        self._timeout_spin.setValue(config.POPUP_TIMEOUT_SEC)

    # ── Signals ──────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._btn_save.clicked.connect(self._on_save)
        self._btn_close.clicked.connect(self.close)

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

            # Temporarily store & validate.
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

        # ── Update target language ───────────────────────
        new_lang = self._lang_combo.currentData()
        if new_lang and new_lang != config.TARGET_LANG:
            config.TARGET_LANG = new_lang

        # ── Update popup timeout ─────────────────────────
        new_timeout = self._timeout_spin.value()
        if new_timeout != config.POPUP_TIMEOUT_SEC:
            config.POPUP_TIMEOUT_SEC = new_timeout

    # ── Rounded dark background ──────────────────────────

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
