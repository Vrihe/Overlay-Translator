"""
ui/subtitles_page.py — the "Subtitles" tab of the main window.

Everything needed to use live subtitles day to day sits on one screen: the start / stop
button, the session status, the audio source, the speech language, streaming mode and
the language filter. What is set up once (the Whisper model and its download, the GPU
libraries, the recognition device) stays in Settings → Subtitles; the page shows the
chosen model and warns when it is not on disk.

Controls save themselves straight into ``config`` and apply the next time subtitles are
started. The page never starts anything itself: the button emits ``toggle_requested``
(handled in main.py) and ``set_active`` / ``set_status`` bring the session state back.
The list of sound devices (PyAudio) is read in ``reload()``, when the tab is opened.
"""

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import config
from i18n import N_, tr
from ui import theme
from ui.hud_widgets import FieldLabel, Panel, SwitchRow, page_title

_logger = logging.getLogger("translator.subtitles")

#: Speech languages offered on the page: Whisper codes; "auto" detects each phrase.
SPEECH_LANGUAGES = [
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


class SubtitlesPage(QWidget):
    #: Start (True) / stop (False) live subtitles.
    toggle_requested = pyqtSignal(bool)
    #: Open Settings → Subtitles (model, downloads, recognition device).
    open_settings_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._loading = False  # True while reload() fills the controls: nothing is saved
        self._build_ui()
        self.reload()

    # ── UI ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        input_css = theme.input_css(9.5) + theme.combo_css(9.5)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(page_title(tr("Субтитры")))

        # Start / stop and the session status.
        run = Panel(tr("Живые субтитры"))
        about = QLabel(
            tr(
                "Распознаёт речь из звука компьютера (стрим, видео, голосовой чат) и показывает "
                "перевод полосой поверх окон. Перевод идёт способом, выбранным в настройках."
            )
        )
        about.setWordWrap(True)
        about.setStyleSheet(theme.label_css("caption"))
        run.body.addWidget(about)
        self._btn_toggle = QPushButton()
        self._btn_toggle.setCursor(Qt.PointingHandCursor)
        self._btn_toggle.setFont(theme.display_font(10, spacing=112))
        self._btn_toggle.setStyleSheet(theme.btn_primary("10px 18px", 10))
        self._btn_toggle.clicked.connect(lambda: self.toggle_requested.emit(not self._active))
        buttons = QHBoxLayout()
        buttons.addWidget(self._btn_toggle)
        buttons.addStretch()
        run.body.addLayout(buttons)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.PlainText)
        run.body.addWidget(self._status)
        root.addWidget(run)

        # Day-to-day parameters.
        params = Panel(tr("Параметры"))
        self._device_combo = QComboBox()
        self._device_combo.setStyleSheet(input_css)
        params.body.addLayout(self._field(tr("Источник звука"), self._device_combo))
        self._lang_combo = QComboBox()
        self._lang_combo.setStyleSheet(input_css)
        for code, name in SPEECH_LANGUAGES:
            self._lang_combo.addItem(f"{tr(name)} ({code})", code)
        params.body.addLayout(self._field(tr("Язык речи"), self._lang_combo))
        self._chk_streaming = SwitchRow(tr("Потоковые субтитры: показывать фразу по ходу речи"))
        self._chk_streaming.setToolTip(
            tr(
                "Перевод появляется примерно раз в секунду, пока человек ещё говорит, и уточняется "
                "в конце фразы. Нагружает видеокарту сильнее, а платный перевод через API "
                "вызывается в несколько раз чаще."
            )
        )
        params.body.addWidget(self._chk_streaming)
        self._chk_skip_foreign = SwitchRow(tr("Пропускать речь на других языках"))
        self._chk_skip_foreign.setToolTip(
            tr(
                "Для голосовых чатов, где говорят на разных языках: фразы не на выбранном языке "
                "речи не показываются. Работает только с многоязычной моделью small."
            )
        )
        params.body.addWidget(self._chk_skip_foreign)
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(theme.text_css(theme.current().warn, 9))
        params.body.addWidget(self._hint)
        applies = QLabel(tr("Новые значения действуют со следующего запуска субтитров."))
        applies.setWordWrap(True)
        applies.setStyleSheet(theme.label_css("caption"))
        params.body.addWidget(applies)
        root.addWidget(params)

        # What is set up once lives in the settings: show it and lead there.
        model = Panel(tr("Модель и видеокарта"))
        self._model_label = QLabel("")
        self._model_label.setWordWrap(True)
        self._model_label.setTextFormat(Qt.PlainText)
        model.body.addWidget(self._model_label)
        self._btn_settings = QPushButton(tr("Настройки"))
        self._btn_settings.setCursor(Qt.PointingHandCursor)
        self._btn_settings.setStyleSheet(theme.btn_accent("6px 12px", 8.5))
        self._btn_settings.clicked.connect(self.open_settings_requested)
        model_buttons = QHBoxLayout()
        model_buttons.addWidget(self._btn_settings)
        model_buttons.addStretch()
        model.body.addLayout(model_buttons)
        root.addWidget(model)
        root.addStretch()

        self._device_combo.currentIndexChanged.connect(lambda _i: self._save("SUBTITLES_DEVICE", self._device()))
        self._lang_combo.currentIndexChanged.connect(lambda _i: self._save("SUBTITLES_LANGUAGE", self._language()))
        self._chk_streaming.toggled.connect(lambda on: self._save("SUBTITLES_STREAMING", bool(on)))
        self._chk_skip_foreign.toggled.connect(lambda on: self._save("SUBTITLES_SKIP_FOREIGN", bool(on)))
        self._update_button()
        self.set_status("")

    @staticmethod
    def _field(caption: str, widget: QWidget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(5)
        box.addWidget(FieldLabel(caption))
        box.addWidget(widget)
        return box

    # ── State from the app ───────────────────────────────

    def set_active(self, active: bool) -> None:
        """Live subtitles started / stopped (also from the tray)."""
        self._active = active
        self._update_button()

    def set_status(self, message: str, kind: str = "info") -> None:
        """The session's last status line (model loading, device, errors)."""
        p = theme.current()
        color = {"ok": p.ok, "warn": p.warn, "error": p.error}.get(kind, p.muted)
        self._status.setText(message)
        self._status.setStyleSheet(theme.text_css(color, 9))
        self._status.setVisible(bool(message))

    def _update_button(self) -> None:
        self._btn_toggle.setText((tr("Остановить субтитры") if self._active else tr("Запустить субтитры")).upper())

    # ── Settings ⇄ controls ──────────────────────────────

    def reload(self) -> None:
        """Show the saved values; called when the tab is opened (settings may have changed)."""
        self._loading = True
        try:
            self._load_devices()
            language = getattr(config, "SUBTITLES_LANGUAGE", "en") or "en"
            self._lang_combo.setCurrentIndex(max(0, self._lang_combo.findData(language)))
            self._chk_streaming.setChecked(bool(getattr(config, "SUBTITLES_STREAMING", False)))
            self._chk_skip_foreign.setChecked(bool(getattr(config, "SUBTITLES_SKIP_FOREIGN", False)))
        finally:
            self._loading = False
        self._refresh_model()

    def _load_devices(self) -> None:
        """Fill the audio source combo: the default output plus every capturable device."""
        saved = getattr(config, "SUBTITLES_DEVICE", "") or ""
        names: list[str] = []
        label = str
        try:
            from audio.capture import display_name, list_loopback_devices

            label = display_name
            names = list(list_loopback_devices())
        except Exception as exc:  # no PyAudio, no audio service: the default device stays selectable
            _logger.info("Sound devices are not listed: %s", type(exc).__name__)
        if saved and saved not in names:
            names.append(saved)  # unplugged right now: keep the choice
        self._device_combo.clear()
        self._device_combo.addItem(tr("Устройство вывода по умолчанию"), "")
        for name in names:
            self._device_combo.addItem(label(name), name)
        self._device_combo.setCurrentIndex(max(0, self._device_combo.findData(saved)))

    def _device(self) -> str:
        return self._device_combo.currentData() or ""

    def _language(self) -> str:
        return self._lang_combo.currentData() or "en"

    def _save(self, name: str, value) -> None:
        if self._loading:
            return
        setattr(config, name, value)
        self._refresh_model()

    def _refresh_model(self) -> None:
        """The chosen model, whether it is on disk, and whether it can do what is asked."""
        from audio import stt

        name = getattr(config, "SUBTITLES_MODEL", "") or stt.DEFAULT_MODEL
        p = theme.current()
        if stt.resolve_model_dir(name) is None:
            self._model_label.setText(
                tr("Модель {name} не скачана — без неё субтитры не запустятся. Скачайте её в настройках.", name=name)
            )
            self._model_label.setStyleSheet(theme.text_css(p.warn, 9))
        else:
            self._model_label.setText(tr("Модель распознавания: {name}", name=name))
            self._model_label.setStyleSheet(theme.text_css(p.muted, 9))
        wants_more = self._chk_skip_foreign.isChecked() or self._language() != "en"
        useless = wants_more and not stt.is_multilingual(name)
        self._hint.setText(
            tr(
                "Модель {name} понимает только английский: для других языков и фильтра языка "
                "выберите многоязычную модель small.",
                name=name,
            )
            if useless
            else ""
        )
        self._hint.setVisible(useless)
