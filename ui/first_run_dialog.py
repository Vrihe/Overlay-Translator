"""
ui/first_run_dialog.py — first-launch dialog for API key setup.

Shown when no API key is found (neither in keyring nor in env vars).
The user picks a provider, enters a key, and the dialog validates it
with a test translation before saving to keyring.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QWidget, QApplication,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath

import settings


class FirstRunDialog(QDialog):
    """Modal dialog for entering an API key on first launch."""

    _WIDTH = 480

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Translator Overlay — Настройка")
        self.setFixedWidth(self._WIDTH)
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._build_ui()
        self._connect_signals()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Card container (for rounded background).
        self._card = QWidget(self)
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # ── Title ──
        title = QLabel("🌐 Добро пожаловать!")
        title.setStyleSheet(self._css("color: #e8e8e8; font-size: 16pt; font-weight: 600;"))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # ── Subtitle ──
        sub = QLabel("Для работы переводчика нужен API-ключ.")
        sub.setStyleSheet(self._css("color: #999; font-size: 10pt;"))
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # ── Provider radio buttons ──
        provider_row = QHBoxLayout()
        provider_row.setSpacing(16)

        self._radio_group = QButtonGroup(self)
        self._radio_or = QRadioButton("OpenRouter (бесплатно)")
        self._radio_ant = QRadioButton("Anthropic (платно)")
        self._radio_or.setChecked(True)
        self._radio_group.addButton(self._radio_or, 0)
        self._radio_group.addButton(self._radio_ant, 1)

        radio_css = self._css("color: #ccc; font-size: 10pt;")
        self._radio_or.setStyleSheet(radio_css)
        self._radio_ant.setStyleSheet(radio_css)

        provider_row.addWidget(self._radio_or)
        provider_row.addWidget(self._radio_ant)
        layout.addLayout(provider_row)

        # ── Link to get a key ──
        self._link_label = QLabel()
        self._link_label.setOpenExternalLinks(True)
        self._link_label.setStyleSheet(self._css("color: #6ba3f7; font-size: 9pt;"))
        self._update_link()
        layout.addWidget(self._link_label)

        # ── Key input ──
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("Вставьте API-ключ…")
        self._key_input.setStyleSheet(
            "QLineEdit {"
            "  background: #2a2a3e; color: #e0e0e0; border: 1px solid #444;"
            "  border-radius: 6px; padding: 8px 12px;"
            "  font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QLineEdit:focus { border-color: #5b8def; }"
        )
        layout.addWidget(self._key_input)

        # ── Status label ──
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))
        layout.addWidget(self._status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._btn_save = QPushButton("Проверить и сохранить")
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(
            "QPushButton {"
            "  background: #5b8def; color: #fff; border: none;"
            "  border-radius: 6px; padding: 9px 20px;"
            "  font-family: 'Segoe UI'; font-size: 10pt; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a7de0; }"
            "QPushButton:disabled { background: #3a3a5c; color: #666; }"
        )
        self._btn_cancel = QPushButton("Отмена")
        self._btn_cancel.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #999; border: 1px solid #444;"
            "  border-radius: 6px; padding: 9px 20px;"
            "  font-family: 'Segoe UI'; font-size: 10pt;"
            "}"
            "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        )

        btn_row.addStretch()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

        root.addWidget(self._card)

    def _connect_signals(self) -> None:
        self._radio_group.buttonClicked.connect(lambda _: self._update_link())
        self._key_input.textChanged.connect(self._on_key_changed)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_cancel.clicked.connect(self.reject)

    # ── Helpers ──────────────────────────────────────────

    def _current_provider(self) -> str:
        return "openrouter" if self._radio_or.isChecked() else "anthropic"

    def _update_link(self) -> None:
        if self._current_provider() == "openrouter":
            url = "https://openrouter.ai/keys"
            text = f'<a href="{url}" style="color:#6ba3f7;">Получить ключ на openrouter.ai →</a>'
        else:
            url = "https://console.anthropic.com/settings/keys"
            text = f'<a href="{url}" style="color:#6ba3f7;">Получить ключ на console.anthropic.com →</a>'
        self._link_label.setText(text)

    def _on_key_changed(self, text: str) -> None:
        self._btn_save.setEnabled(bool(text.strip()))
        self._status.setText("")
        self._status.setStyleSheet(self._css("color: #999; font-size: 9pt;"))

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        color = "#ff6b6b" if error else "#66cc99"
        self._status.setText(msg)
        self._status.setStyleSheet(self._css(f"color: {color}; font-size: 9pt;"))

    @staticmethod
    def _css(extra: str) -> str:
        return f"font-family: 'Segoe UI'; background: transparent; {extra}"

    # ── Save with validation ─────────────────────────────

    def _on_save(self) -> None:
        key = self._key_input.text().strip()
        if not key:
            return

        provider = self._current_provider()
        self._btn_save.setEnabled(False)
        self._set_status("Проверяем ключ…")
        QApplication.processEvents()

        # Temporarily save the key so translate() can pick it up.
        settings.set_api_key(provider, key)

        # Force the LLM client to re-create with the new key.
        from translate.llm_client import translate, reset_client
        reset_client()

        try:
            result = translate("Hello", target_lang="ru")
            if not result:
                raise RuntimeError("Пустой ответ от API")
        except Exception as e:
            # Roll back — remove the invalid key.
            settings.delete_api_key(provider)
            reset_client()
            self._set_status(f"Ошибка: {e}", error=True)
            self._btn_save.setEnabled(True)
            return

        self._set_status("✓ Ключ работает! Сохранено.")
        QApplication.processEvents()

        # Brief delay so the user sees the success message.
        QTimer.singleShot(800, self.accept)

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
