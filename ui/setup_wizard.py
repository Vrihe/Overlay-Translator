"""
ui/setup_wizard.py — first-run wizard: how to translate, then where the hotkeys are.

Page "mode" offers three ways to translate:
  • online without a key — Google Translate (the default backend),
  • a neural network with an API key — the LLM backend; main.py asks for the key
    right after the wizard (``FirstRunDialog``),
  • offline — the local NLLB model: page "offline" lists the builds (local copies and
    Hugging Face tags) and downloads the chosen one with progress and a SHA-256 check.
Page "done" shows the hotkeys. "Start" saves the choice; closing the wizard keeps the
defaults. Either way ``first_run_done`` is set by the caller (main.py) or here.
"""

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from i18n import tr
from settings import config_manager
from ui import theme
from ui.hud_widgets import FieldLabel
from ui.nllb_workers import NllbDownloadWorker, NllbVersionsWorker

log = logging.getLogger(__name__)

MODE_ONLINE = "online"
MODE_LLM = "llm"
MODE_OFFLINE = "offline"
BACKEND_FOR_MODE = {MODE_ONLINE: "google", MODE_LLM: "api", MODE_OFFLINE: "nllb"}

_PAGE_MODE, _PAGE_OFFLINE, _PAGE_DONE = range(3)

# Workers of a closed wizard: a running QThread that loses its last reference aborts
# the process, so they are parked here, detached from the dialog, until they finish.
_finishing: set = set()


def _keep_until_finished(worker) -> None:
    if hasattr(worker, "cancel"):
        worker.cancel.set()
    for name in ("finished_with_status", "finished_with_versions", "progress_changed"):
        signal = getattr(worker, name, None)
        if signal is not None:
            try:
                signal.disconnect()
            except TypeError:
                pass  # nothing connected
    worker.setParent(None)
    _finishing.add(worker)
    worker.finished.connect(lambda w=worker: _finishing.discard(w))


def apply_choice(mode: str, model_path: str = "") -> None:
    """Save the wizard's choice: the backend, the offline model path, the done flag."""
    config_manager.set_value("translation_backend", BACKEND_FOR_MODE[mode])
    if mode == MODE_OFFLINE and model_path:
        config_manager.set_value("nllb_model_path", model_path)
    config_manager.set_value("first_run_done", True)


def build_entries(local: list, remote: list | None) -> list[tuple[str, tuple]]:
    """Combo entries ``(label, (kind, value))`` for the offline page.

    Local copies first (``("local", path)``), then published builds that are not
    on disk yet (``("remote", RemoteVersion)``).
    """
    from translate.nllb_models import match_local

    entries = []
    for model in local:
        name = model.tag or model.path.name
        entries.append((tr("{tag} — скачана", tag=name), ("local", str(model.path))))
    for version in remote or []:
        if match_local(version.tag, local) is None:
            entries.append((tr("{tag} — скачать (~600 МБ)", tag=version.tag), ("remote", version)))
    return entries


def preferred_index(entries: list[tuple[str, tuple]], pinned_sha: str) -> int:
    """The entry to preselect: the app's pinned build if listed, else the newest build."""
    for i, (_label, (kind, value)) in enumerate(entries):
        if kind == "remote" and value.sha == pinned_sha:
            return i
    return len(entries) - 1 if entries else -1


class SetupWizard(QDialog):
    """Modal first-run wizard. ``exec_()`` returns Accepted once the choice is saved."""

    _WIDTH = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Translator Overlay — Настройка"))
        self.setFixedWidth(self._WIDTH)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._mode = MODE_ONLINE
        self._model_path = ""
        self._remote_versions = None
        self._versions_worker = None
        self._download_worker = None

        self._build_ui()
        self._show_page(_PAGE_MODE)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        p = theme.current()
        title = QLabel(f"<span style='color:{p.accent};'>//</span> " + tr("Добро пожаловать!").upper())
        title.setTextFormat(Qt.RichText)
        title.setFont(theme.display_font(16, spacing=106))
        title.setStyleSheet(f"color: {p.text}; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_mode_page())
        self._pages.addWidget(self._build_offline_page())
        self._pages.addWidget(self._build_done_page())
        layout.addWidget(self._pages)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self._btn_back = QPushButton(tr("Назад"))
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.setStyleSheet(theme.btn_secondary("9px 20px", 9.5))
        self._btn_back.clicked.connect(self._on_back)
        self._btn_next = QPushButton()
        self._btn_next.setCursor(Qt.PointingHandCursor)
        self._btn_next.setFont(theme.display_font(10, spacing=110))
        self._btn_next.setStyleSheet(theme.btn_primary("9px 20px", 10))
        self._btn_next.clicked.connect(self._on_next)
        buttons.addWidget(self._btn_back)
        buttons.addStretch()
        buttons.addWidget(self._btn_next)
        layout.addLayout(buttons)

        root.addWidget(card)

    def _text(self, text: str, color: str | None = None, pt: float = 9.5) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        label.setStyleSheet(theme.text_css(color or theme.current().text_soft, pt))
        return label

    def _build_mode_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        p = theme.current()
        layout.addWidget(
            self._text(tr("Как переводить текст с экрана? Это можно поменять в любой момент в настройках."))
        )

        self._mode_group = QButtonGroup(self)
        choices = [
            (
                MODE_ONLINE,
                tr("Онлайн, без ключа — Google Translate"),
                tr("Работает сразу. Распознанный текст отправляется в Google."),
            ),
            (
                MODE_LLM,
                tr("Нейросеть со своим API-ключом"),
                tr(
                    "OpenRouter или Anthropic: лучше понимает сленг и контекст игр. Ключ OpenRouter "
                    "можно получить бесплатно. DeepL и Azure подключаются в настройках."
                ),
            ),
            (
                MODE_OFFLINE,
                tr("Офлайн — локальная модель NLLB"),
                tr("Текст не покидает компьютер. Нужно один раз скачать модель (~600 МБ)."),
            ),
        ]
        for i, (mode, caption, hint) in enumerate(choices):
            radio = QRadioButton(caption)
            radio.setStyleSheet(theme.check_css(10))
            radio.setProperty("mode", mode)
            self._mode_group.addButton(radio, i)
            layout.addSpacing(4)
            layout.addWidget(radio)
            hint_label = self._text(hint, p.muted, 8.5)
            hint_label.setContentsMargins(22, 0, 0, 0)
            layout.addWidget(hint_label)
        self._mode_group.button(0).setChecked(True)
        return page

    def _build_offline_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._text(tr("Выберите версию модели. Её нужно скачать один раз, дальше перевод работает без интернета."))
        )

        layout.addWidget(FieldLabel(tr("Версия модели")))
        row = QHBoxLayout()
        self._version_combo = QComboBox()
        self._version_combo.setStyleSheet(theme.input_css(10, "6px 10px"))
        self._version_combo.currentIndexChanged.connect(self._update_offline_state)
        self._btn_download = QPushButton(tr("Скачать"))
        self._btn_download.setCursor(Qt.PointingHandCursor)
        self._btn_download.setStyleSheet(theme.btn_accent("7px 14px", 9))
        self._btn_download.clicked.connect(self._on_download_clicked)
        row.addWidget(self._version_combo, 1)
        row.addWidget(self._btn_download)
        layout.addLayout(row)

        p = theme.current()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background: {p.bg}; border: 1px solid {p.line}; border-radius: 0; }}"
            f"QProgressBar::chunk {{ background: {p.accent}; }}"
        )
        self._progress.hide()
        layout.addWidget(self._progress)

        self._offline_status = self._text("", p.muted, 9)
        layout.addWidget(self._offline_status)
        layout.addStretch()
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        p = theme.current()
        hotkey = str(getattr(config, "HOTKEY", "ctrl+shift+r")).upper()
        settings_hotkey = str(getattr(config, "SETTINGS_HOTKEY", "ctrl+shift+o")).upper()
        layout.addWidget(self._text(tr("Всё готово. Как пользоваться:"), p.text, 10))
        layout.addWidget(self._text(tr("1. Нажмите {hotkey} и выделите область экрана с текстом.", hotkey=hotkey)))
        layout.addWidget(self._text(tr("2. Перевод появится рядом с выделенной областью.")))
        layout.addWidget(
            self._text(
                tr("3. Настройки — {hotkey} или значок приложения в трее рядом с часами.", hotkey=settings_hotkey)
            )
        )
        layout.addStretch()
        return page

    # ── Navigation ───────────────────────────────────────

    def _show_page(self, page: int) -> None:
        self._pages.setCurrentIndex(page)
        self._btn_back.setVisible(page != _PAGE_MODE)
        self._btn_next.setText((tr("Начать") if page == _PAGE_DONE else tr("Далее")).upper())
        if page == _PAGE_OFFLINE:
            self._load_offline_entries()
        self._update_offline_state()
        self.adjustSize()

    def _selected_mode(self) -> str:
        return self._mode_group.checkedButton().property("mode")

    def _on_back(self) -> None:
        if self._download_worker is not None:
            return  # cancel the download first
        page = self._pages.currentIndex()
        if page == _PAGE_DONE and self._mode == MODE_OFFLINE:
            self._show_page(_PAGE_OFFLINE)
        else:
            self._show_page(_PAGE_MODE)

    def _on_next(self) -> None:
        page = self._pages.currentIndex()
        if page == _PAGE_MODE:
            self._mode = self._selected_mode()
            self._show_page(_PAGE_OFFLINE if self._mode == MODE_OFFLINE else _PAGE_DONE)
        elif page == _PAGE_OFFLINE:
            kind, value = self._version_combo.currentData() or (None, None)
            if kind == "local":
                self._model_path = value
                self._show_page(_PAGE_DONE)
        else:
            apply_choice(self._mode, self._model_path)
            log.info("First-run wizard finished: mode=%s", self._mode)
            self.accept()

    # ── Offline page ─────────────────────────────────────

    def _load_offline_entries(self, select_path: str = "") -> None:
        from translate.nllb_models import list_local_models

        entries = build_entries(list_local_models(), self._remote_versions)
        self._version_combo.blockSignals(True)
        self._version_combo.clear()
        for label, data in entries:
            self._version_combo.addItem(label, data)
        index = next(
            (i for i, (_l, (kind, value)) in enumerate(entries) if kind == "local" and value == select_path), -1
        )
        if index < 0:
            index = preferred_index(entries, getattr(config, "NLLB_HF_REVISION", ""))
        self._version_combo.setCurrentIndex(index)
        self._version_combo.blockSignals(False)

        if self._remote_versions is None and self._versions_worker is None:
            self._set_offline_status(tr("Загружаем список версий…"))
            self._versions_worker = NllbVersionsWorker(self)
            self._versions_worker.finished_with_versions.connect(self._on_versions_fetched)
            self._versions_worker.start()
        self._update_offline_state()

    def _on_versions_fetched(self, versions, error: str) -> None:
        self._versions_worker = None
        if versions is None:
            self._set_offline_status(tr("⚠ Не удалось получить список версий: {error}", error=error), "warn")
            if self._version_combo.count() == 0:
                self._btn_download.setText(tr("Повторить"))
            return
        self._remote_versions = versions
        self._set_offline_status("")
        if self._pages.currentIndex() == _PAGE_OFFLINE:
            self._load_offline_entries()

    def _update_offline_state(self) -> None:
        if self._pages.currentIndex() != _PAGE_OFFLINE:
            self._btn_next.setEnabled(True)
            return
        kind, value = self._version_combo.currentData() or (None, None)
        downloading = self._download_worker is not None
        self._btn_next.setEnabled(kind == "local" and not downloading)
        self._btn_back.setEnabled(not downloading)
        self._version_combo.setEnabled(not downloading)
        if downloading:
            self._btn_download.setText(tr("Отмена"))
            self._btn_download.setVisible(True)
        elif kind == "remote":
            self._btn_download.setText(tr("Скачать"))
            self._btn_download.setVisible(True)
        else:
            # No entries: offer a retry of the version list; a local copy needs no button.
            self._btn_download.setText(tr("Повторить"))
            self._btn_download.setVisible(kind is None and self._versions_worker is None)
        if kind == "local" and not downloading:
            self._set_offline_status(tr("✓ Модель на диске, можно продолжать."), "ok")

    def _on_download_clicked(self) -> None:
        if self._download_worker is not None:
            self._download_worker.cancel.set()
            return
        kind, value = self._version_combo.currentData() or (None, None)
        if kind != "remote":
            self._load_offline_entries()  # retry the version list
            return
        self._progress.setValue(0)
        self._progress.show()
        self._set_offline_status(tr("⏳ Скачивание {tag}…", tag=value.tag))
        self._download_worker = NllbDownloadWorker(value, self)
        self._download_worker.progress_changed.connect(
            lambda pct, done, total: self._on_download_progress(value.tag, pct, done, total)
        )
        self._download_worker.finished_with_status.connect(self._on_download_done)
        self._download_worker.start()
        self._update_offline_state()

    def _on_download_progress(self, tag: str, pct: int, done: int, total: int) -> None:
        self._progress.setValue(pct)
        self._set_offline_status(
            tr("⏳ Скачивание {tag}: {done} / {total} МБ ({pct}%)", tag=tag, done=done, total=total, pct=pct)
        )

    def _on_download_done(self, ok: bool, result: str) -> None:
        self._download_worker = None
        self._progress.hide()
        if ok:
            self._load_offline_entries(select_path=result)
        elif result:
            self._set_offline_status(tr("⚠ Не удалось скачать модель: {error}", error=result), "warn")
        else:
            self._set_offline_status(tr("Скачивание отменено."))
        self._update_offline_state()

    def _set_offline_status(self, text: str, kind: str = "muted") -> None:
        p = theme.current()
        color = {"ok": p.ok, "warn": p.warn}.get(kind, p.muted)
        self._offline_status.setText(text)
        self._offline_status.setStyleSheet(theme.text_css(color, 9))

    # ── Closing ──────────────────────────────────────────

    def reject(self) -> None:
        """Closing cancels a download; running workers outlive the dialog until they end."""
        for worker in (self._download_worker, self._versions_worker):
            if worker is not None and worker.isRunning():
                _keep_until_finished(worker)
        self._download_worker = self._versions_worker = None
        super().reject()

    # ── Square HUD background ────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(r, theme.qcolor("panel"))
        painter.setPen(QPen(theme.qcolor("line"), 1))
        painter.drawRect(r)
        painter.fillRect(0, 0, self.width(), 2, theme.qcolor("accent"))
        painter.end()
