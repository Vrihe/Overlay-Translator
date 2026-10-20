"""
ui/first_run_dialog.py — first-launch dialog for API key setup.

Shown when no API key is found (neither in keyring nor in env vars).
The user picks a provider, enters a key, and the dialog checks it with that
provider before saving it to keyring.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QButtonGroup, QWidget, QApplication,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen

import settings
from i18n import tr
from ui import theme
from ui.hud_widgets import FieldLabel


class FirstRunDialog(QDialog):
    """Modal dialog for entering an API key on first launch."""

    _WIDTH = 480

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(tr("Translator Overlay — Настройка"))
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

        p = theme.current()

        # Card container (painted background, see paintEvent).
        self._card = QWidget(self)
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # ── Title ──
        title = QLabel(f"<span style='color:{p.accent};'>//</span> " + tr("Добро пожаловать!").upper())
        title.setTextFormat(Qt.RichText)
        title.setFont(theme.display_font(16, spacing=106))
        title.setStyleSheet(f"color: {p.text}; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # ── Subtitle ──
        sub = QLabel(tr("Для работы переводчика нужен API-ключ."))
        sub.setStyleSheet(theme.text_css(p.text_soft, 9.5))
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # ── Privacy notice: screen text leaves the machine ──
        privacy = QLabel(tr(
            "Распознанный текст выделенной области отправляется выбранному провайдеру. "
            "Бесплатные модели OpenRouter могут сохранять запросы. Не переводите пароли "
            "и личные данные или используйте локальную модель NLLB (Настройки → Бэкенд перевода)."
        ))
        privacy.setTextFormat(Qt.PlainText)
        privacy.setWordWrap(True)
        privacy.setStyleSheet(
            theme.text_css(p.warn, 8.5) + f" border: 1px solid {theme.rgba(p.warn, 70)}; padding: 8px;"
        )
        layout.addWidget(privacy)

        # ── Provider radio buttons ──
        layout.addWidget(FieldLabel(tr("Провайдер")))
        provider_row = QHBoxLayout()
        provider_row.setSpacing(16)

        self._radio_group = QButtonGroup(self)
        self._radio_or = QRadioButton(tr("OpenRouter (бесплатно)"))
        self._radio_ant = QRadioButton(tr("Anthropic (платно)"))
        self._radio_or.setChecked(True)
        self._radio_group.addButton(self._radio_or, 0)
        self._radio_group.addButton(self._radio_ant, 1)

        radio_css = theme.check_css(9.5)
        self._radio_or.setStyleSheet(radio_css)
        self._radio_ant.setStyleSheet(radio_css)

        provider_row.addWidget(self._radio_or)
        provider_row.addWidget(self._radio_ant)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        # ── Link to get a key ──
        self._link_label = QLabel()
        self._link_label.setOpenExternalLinks(True)
        self._link_label.setStyleSheet(theme.text_css(p.accent, 9))
        self._update_link()
        layout.addWidget(self._link_label)

        # ── Key input ──
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText(tr("Вставьте API-ключ…"))
        self._key_input.setStyleSheet(theme.input_css(10, "8px 12px"))
        layout.addWidget(self._key_input)

        # ── Status label ──
        self._status = QLabel("")
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(self._css(p.muted))
        layout.addWidget(self._status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._btn_save = QPushButton(tr("Проверить и сохранить").upper())
        self._btn_save.setEnabled(False)
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setFont(theme.display_font(10, spacing=110))
        self._btn_save.setStyleSheet(theme.btn_primary("9px 20px", 10))
        self._btn_cancel = QPushButton(tr("Отмена"))
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setStyleSheet(theme.btn_secondary("9px 20px", 9.5))

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
            caption = tr("Получить ключ на openrouter.ai →")
        else:
            url = "https://console.anthropic.com/settings/keys"
            caption = tr("Получить ключ на console.anthropic.com →")
        self._link_label.setText(f'<a href="{url}" style="color:{theme.current().accent};">{caption}</a>')

    def _on_key_changed(self, text: str) -> None:
        self._btn_save.setEnabled(bool(text.strip()))
        self._status.setText("")
        self._status.setStyleSheet(self._css(theme.current().muted))

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        p = theme.current()
        self._status.setText(msg)
        self._status.setStyleSheet(self._css(p.error if error else p.ok))

    @staticmethod
    def _css(color: str) -> str:
        return theme.text_css(color, 9)

    # ── Save with validation ─────────────────────────────

    def _on_save(self) -> None:
        key = self._key_input.text().strip()
        if not key:
            return

        provider = self._current_provider()
        self._btn_save.setEnabled(False)
        self._set_status(tr("Проверяем ключ…"))
        QApplication.processEvents()

        from translate.llm_client import validate_api_key, reset_client
        try:
            validate_api_key(provider, key)
        except Exception as e:
            self._set_status(tr("Ошибка: {error}", error=e), error=True)
            self._btn_save.setEnabled(True)
            return

        settings.set_api_key(provider, key)
        reset_client()

        self._set_status(tr("✓ Ключ работает! Сохранено."))
        QApplication.processEvents()

        # Brief delay so the user sees the success message.
        QTimer.singleShot(800, self.accept)

    # ── Square HUD background ────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(r, theme.qcolor("panel"))
        painter.setPen(QPen(theme.qcolor("line"), 1))
        painter.drawRect(r)
        painter.fillRect(0, 0, self.width(), 2, theme.qcolor("accent"))
        painter.end()
