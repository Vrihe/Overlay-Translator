"""
ui/subtitles_page.py — the "Subtitles" tab of the main window.

Everything about live subtitles is on this one screen: the start / stop button, the session
status, the Python packages (an install button when faster-whisper or PyAudioWPatch is
missing, source runs only), the speech model (choice, download, recognition device, GPU libraries, video
memory) and the day-to-day parameters (audio source, speech language, streaming mode,
language filter). Nothing has to be looked up in Settings.

When subtitles cannot start for lack of packages or a model, the button does not start
anything: it says so, selects the model that is needed and moves to the install / download button. The same page
is opened by the app when a start from the tray fails (``MainWindow.show_and_switch``).

Controls save themselves straight into ``config``. Subtitles that are running are
restarted shortly after a change (stop, then start, through ``toggle_requested``), so the
new value is what is on screen. The page never starts anything itself: the button emits
``toggle_requested`` (handled in main.py) and ``set_active`` / ``set_status`` bring the
session state back. Models and libraries are downloaded only by their buttons. The list
of sound devices (PyAudio) is read in ``reload()``, when the tab is opened.
"""

import logging

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

import config
from i18n import N_, tr
from ui import theme
from ui.hud_widgets import FieldLabel, Panel, SwitchRow, page_title
from ui.nllb_workers import SpeechCudaDownloadWorker, SpeechModelDownloadWorker, SpeechPackagesInstallWorker

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


#: Whisper models offered (audio/stt.py looks for models/whisper-<name>); the first is the default.
SUBTITLE_MODELS = [
    ("small.en", N_("small.en — точнее, нужна видеокарта NVIDIA")),
    ("small", N_("small — многоязычная, для фильтра языка; нужна видеокарта NVIDIA")),
    ("large-v3-turbo", N_("large-v3-turbo — многоязычная, заметно точнее и почти так же быстра; 1,5 ГБ")),
    ("large-v3", N_("large-v3 — самая точная, медленнее; 3 ГБ, видеокарта от 6 ГБ памяти")),
    ("base.en", N_("base.en — быстрее, подходит для процессора")),
    ("tiny.en", N_("tiny.en — самая быстрая, больше ошибок")),
]

#: Running subtitles restart this long after the last change of a parameter.
RESTART_DELAY_MS = 700


class SubtitlesPage(QWidget):
    #: Start (True) / stop (False) live subtitles.
    toggle_requested = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._loading = False  # True while reload() fills the controls: nothing is saved
        self._packages_worker = None  # running pip install
        self._model_worker = None  # running model download
        self._gpu_worker = None  # running GPU-library download
        self._gpu_stage = "cuDNN"
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(RESTART_DELAY_MS)
        self._restart_timer.timeout.connect(self._restart)
        self._build_ui()
        self.reload()

    # ── UI ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        input_css = theme.input_css(9.5) + theme.combo_css(9.5)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(self._scroll)
        content = QWidget()
        content.setObjectName("subtitlesContent")
        content.setStyleSheet("#subtitlesContent { background: transparent; }")
        self._scroll.setWidget(content)
        root = QVBoxLayout(content)
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
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        buttons = QHBoxLayout()
        buttons.addWidget(self._btn_toggle)
        buttons.addStretch()
        run.body.addLayout(buttons)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.PlainText)
        run.body.addWidget(self._status)
        root.addWidget(run)

        # Day-to-day parameters (added below the model panel).
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
        applies = QLabel(tr("Изменения применяются сразу: работающие субтитры перезапускаются."))
        applies.setWordWrap(True)
        applies.setStyleSheet(theme.label_css("caption"))
        params.body.addWidget(applies)

        # Python packages: shown only while something is missing (a source run without install.bat).
        self._packages_panel = Panel(tr("Компоненты"))
        self._packages_status, self._btn_packages, packages_row = self._download_row(self._on_packages_clicked)
        self._packages_panel.body.addWidget(packages_row)
        root.addWidget(self._packages_panel)

        # The speech model: choice, download, recognition device, GPU libraries, video memory.
        self._model_panel = Panel(tr("Модель распознавания"))
        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(input_css)
        for model, label in SUBTITLE_MODELS:
            self._model_combo.addItem(tr(label), model)
        self._model_panel.body.addLayout(self._field(tr("Модель"), self._model_combo))
        self._model_status, self._btn_model, model_row = self._download_row(self._on_model_clicked)
        self._model_panel.body.addWidget(model_row)
        self._stt_device_combo = QComboBox()
        self._stt_device_combo.setStyleSheet(input_css)
        self._stt_device_combo.addItem(tr("Авто (видеокарта NVIDIA, если доступна)"), "auto")
        self._stt_device_combo.addItem(tr("Только процессор (CPU)"), "cpu")
        self._model_panel.body.addLayout(self._field(tr("Устройство распознавания"), self._stt_device_combo))
        self._gpu_status, self._btn_gpu, self._gpu_widget = self._download_row(self._on_gpu_clicked)
        self._model_panel.body.addWidget(self._gpu_widget)
        self._chk_low_vram = SwitchRow(tr("Экономить видеопамять (сжатие int8)"))
        self._chk_low_vram.setToolTip(
            tr(
                "Модель загружается на видеокарту в сжатом виде: видеопамяти нужно примерно вдвое "
                "меньше, а точность распознавания слегка падает. Файл модели на диске не меняется."
            )
        )
        self._model_panel.body.addWidget(self._chk_low_vram)
        self._vram_hint = QLabel("")
        self._vram_hint.setWordWrap(True)
        self._vram_hint.setStyleSheet(theme.label_css("caption"))
        self._model_panel.body.addWidget(self._vram_hint)
        root.addWidget(self._model_panel)
        root.addWidget(params)
        root.addStretch()

        self._model_combo.currentIndexChanged.connect(lambda _i: self._save("SUBTITLES_MODEL", self._model()))
        self._stt_device_combo.currentIndexChanged.connect(
            lambda _i: self._save("SUBTITLES_STT_DEVICE", self._stt_device_combo.currentData() or "auto")
        )
        self._chk_low_vram.toggled.connect(lambda on: self._save("SUBTITLES_LOW_VRAM", bool(on)))
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
            model = getattr(config, "SUBTITLES_MODEL", "") or SUBTITLE_MODELS[0][0]
            self._model_combo.setCurrentIndex(max(0, self._model_combo.findData(model)))
            device = getattr(config, "SUBTITLES_STT_DEVICE", "auto") or "auto"
            self._stt_device_combo.setCurrentIndex(max(0, self._stt_device_combo.findData(device)))
            self._chk_low_vram.setChecked(bool(getattr(config, "SUBTITLES_LOW_VRAM", False)))
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
        if self._active:
            self._restart_timer.start()

    def _restart(self) -> None:
        """Apply changed parameters to subtitles that are running."""
        if self._active:
            self.toggle_requested.emit(False)
            self.toggle_requested.emit(True)

    def _model(self) -> str:
        return self._model_combo.currentData() or SUBTITLE_MODELS[0][0]

    def _refresh_model(self) -> None:
        """The model rows, the memory hint and whether the model can do what is asked."""
        from audio import stt

        name = self._model()
        self._refresh_packages()
        self._refresh_model_row()
        self._refresh_gpu_row()
        self._refresh_vram_hint()
        wants_more = self._chk_skip_foreign.isChecked() or self._language() != "en"
        useless = wants_more and not stt.is_multilingual(name)
        self._hint.setText(
            tr(
                "Модель {name} понимает только английский: для других языков и фильтра языка "
                "выберите многоязычную модель small.",
                name=name,
            )
            if useless and not self._multilingual_ready(name)
            else ""
        )
        self._hint.setVisible(bool(self._hint.text()))

    def _multilingual_ready(self, name: str) -> bool:
        """Another speech language with an English-only model: the session swaps in the
        multilingual one when it is on disk (audio/session.py), so there is nothing to warn about."""
        from audio import session, stt

        return self._language() != "en" and stt.resolve_model_dir(session.MULTILINGUAL_MODEL) is not None

    # ── Starting: the model must be there ────────────────

    def _needed_model(self) -> str:
        """The model the session will load for the chosen language (audio/session.py rule)."""
        from audio import session, stt

        name = self._model()
        if self._language() != "en" and not stt.is_multilingual(name):
            return session.MULTILINGUAL_MODEL
        return name

    def _on_toggle_clicked(self) -> None:
        if self._active:
            self.toggle_requested.emit(False)
            return
        if self._model_worker is not None:
            self.show_model_problem(tr("Модель ещё скачивается. Дождитесь окончания загрузки."))
            return
        from audio import stt

        self._refresh_packages()
        if self._packages_message():
            self._show_problem(self._packages_message(), self._packages_panel, self._btn_packages)
            return
        needed = self._needed_model()
        if stt.resolve_model_dir(needed) is not None:
            self.toggle_requested.emit(True)
            return
        # Not started: say why and lead to the download button. A model other than the chosen
        # one is selected (and saved) when the speech language needs it.
        if needed != self._model():
            self._model_combo.setCurrentIndex(max(0, self._model_combo.findData(needed)))
        self._refresh_model()
        self.show_model_problem(tr("Для запуска нужна модель {name}. Скачайте её кнопкой ниже.", name=needed))

    def on_start_failed(self, message: str) -> None:
        """Subtitles did not start: a missing model leads to its download, anything else is shown."""
        from audio import stt

        self._refresh_packages()
        if self._packages_message():
            self._show_problem(self._packages_message(), self._packages_panel, self._btn_packages)
            return
        needed = self._needed_model()
        if stt.resolve_model_dir(needed) is None:
            if needed != self._model():
                self._model_combo.setCurrentIndex(max(0, self._model_combo.findData(needed)))
            self._refresh_model()
            self.show_model_problem(tr("Для запуска нужна модель {name}. Скачайте её кнопкой ниже.", name=needed))
        else:
            self.set_status(message, "error")

    def show_model_problem(self, message: str) -> None:
        """Tell the user what is missing and bring the model panel (its button) into view."""
        target = self._btn_model if not self._btn_model.isHidden() else self._model_combo
        self._show_problem(message, self._model_panel, target)

    def _show_problem(self, message: str, panel: QWidget, target: QWidget) -> None:
        self.set_status(message, "warn")
        self._scroll.ensureWidgetVisible(panel, 0, 20)
        target.setFocus(Qt.OtherFocusReason)

    # ── Python packages ──────────────────────────────────

    def _packages_message(self) -> str:
        """What to do about missing packages; "" when none is missing."""
        from audio import packages

        missing = packages.missing_packages()
        if not missing:
            return ""
        if packages.can_install():
            return tr(
                "Не установлены пакеты: {names}. Без них субтитры не работают — нажмите «Установить пакеты».",
                names=", ".join(missing),
            )
        return tr(
            "Не установлены пакеты: {names}. Переустановите приложение или запустите install.bat.",
            names=", ".join(missing),
        )

    def _refresh_packages(self) -> None:
        if self._packages_worker is not None:
            return  # the install progress owns the row
        from audio import packages

        message = self._packages_message()
        self._packages_panel.setVisible(bool(message))
        self._btn_packages.setVisible(bool(message) and packages.can_install())
        self._btn_packages.setText(tr("Установить пакеты"))
        if message:
            self._set_row(self._packages_status, message, "warn")

    def _on_packages_clicked(self) -> None:
        if self._packages_worker is not None:
            self._packages_worker.cancel.set()
            return
        self._btn_packages.setText(tr("Отмена"))
        self._set_row(
            self._packages_status,
            tr("⏳ Установка пакетов (pip)… Это может занять несколько минут, нужен интернет."),
        )
        self._packages_worker = SpeechPackagesInstallWorker(self)
        self._packages_worker.finished_with_status.connect(self._on_packages_done)
        self._packages_worker.start()

    def _on_packages_done(self, ok: bool, error: str) -> None:
        self._packages_worker = None
        self._refresh_packages()
        self._refresh_model()
        if ok:
            self.set_status(tr("Пакеты установлены. Осталось скачать модель и запустить субтитры."), "ok")
        elif error:
            self._set_row(self._packages_status, tr("⚠ Не удалось установить пакеты: {error}", error=error), "warn")
        else:
            self._set_row(self._packages_status, tr("Установка отменена."))

    # ── Rows with a download button ──────────────────────

    @staticmethod
    def _download_row(on_click):
        """A status label with a download button on the right: ``(label, button, row widget)``."""
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        status = QLabel("")
        status.setWordWrap(True)
        status.setTextFormat(Qt.PlainText)
        row.addWidget(status, 1)
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(theme.btn_accent("6px 12px", 8.5))
        button.clicked.connect(on_click)
        row.addWidget(button, 0, Qt.AlignTop)
        return status, button, row_widget

    @staticmethod
    def _set_row(label: QLabel, message: str, kind: str = "muted") -> None:
        label.setText(message)
        label.setStyleSheet(theme.text_css(getattr(theme.current(), kind), 9))

    def _refresh_vram_hint(self) -> None:
        """How much video memory the chosen model takes, with and without the int8 switch."""
        from audio import stt

        name = self._model()
        normal, low = stt.VRAM_MB.get(name, (0, 0))
        if not normal:
            self._vram_hint.setText("")
        elif self._chk_low_vram.isChecked():
            self._vram_hint.setText(
                tr(
                    "Модель {name} займёт около {low} МБ видеопамяти вместо {normal} МБ. "
                    "Качество распознавания слегка упадёт.",
                    name=name,
                    low=low,
                    normal=normal,
                )
            )
        else:
            self._vram_hint.setText(
                tr(
                    "Модель {name} займёт около {normal} МБ видеопамяти; с экономией — около {low} МБ.",
                    name=name,
                    low=low,
                    normal=normal,
                )
            )
        self._vram_hint.setVisible(bool(self._vram_hint.text()))

    # Speech model download.

    def _refresh_model_row(self) -> None:
        if self._model_worker is not None:
            return  # the download progress owns the row
        from audio import stt, stt_download

        name = self._model()
        installed = stt.resolve_model_dir(name) is not None
        self._btn_model.setText(tr("Скачать модель"))
        self._btn_model.setVisible(not installed and stt_download.is_downloadable(name))
        if installed:
            self._set_row(self._model_status, tr("✓ Модель {name} установлена.", name=name), "ok")
        else:
            self._set_row(
                self._model_status,
                tr(
                    "Модель {name} не скачана: ~{size} МБ. Без неё субтитры не запустятся.",
                    name=name,
                    size=stt_download.APPROX_MB.get(name, "?"),
                ),
                "warn",
            )

    def _on_model_clicked(self) -> None:
        if self._model_worker is not None:
            self._model_worker.cancel.set()
            return
        name = self._model()
        self._btn_model.setText(tr("Отмена"))
        self._model_combo.setEnabled(False)
        self._set_row(self._model_status, tr("⏳ Скачивание модели {name}…", name=name))
        self._model_worker = SpeechModelDownloadWorker(name, self)
        self._model_worker.progress_changed.connect(
            lambda pct, done, total: self._set_row(
                self._model_status,
                tr("⏳ Скачивание модели: {done} / {total} МБ ({pct}%)", done=done, total=total, pct=pct),
            )
        )
        self._model_worker.finished_with_status.connect(self._on_model_done)
        self._model_worker.start()

    def _on_model_done(self, ok: bool, result: str) -> None:
        self._model_worker = None
        self._model_combo.setEnabled(True)
        self._refresh_model()
        if ok:
            self.set_status(tr("Модель скачана. Можно запускать субтитры."), "ok")
        else:
            self._set_row(
                self._model_status,
                tr("⚠ Не удалось скачать модель: {error}", error=result) if result else tr("Скачивание отменено."),
                "warn" if result else "muted",
            )

    # GPU libraries for speech recognition (cuDNN, cuBLAS).

    def _refresh_gpu_row(self) -> None:
        if self._gpu_worker is not None:
            return  # the download progress owns the row
        from audio import stt
        from translate.cuda_download import driver_cuda_version, gpu_offer
        from translate.cuda_support import find_cublas_dir

        ready = stt.find_cudnn_dir() is not None and find_cublas_dir() is not None
        offer = gpu_offer(driver_cuda_version(), ready)
        self._gpu_widget.setVisible(offer != "none")
        self._btn_gpu.setText(tr("Скачать для видеокарты"))
        self._btn_gpu.setVisible(offer == "download")
        label = self._gpu_status
        if offer == "ready" and self._stt_device_combo.currentData() == "cpu":
            self._set_row(label, tr("Библиотеки CUDA есть, но выбрано «Только процессор»: видеокарта не используется."))
        elif offer == "ready":
            self._set_row(label, tr("✓ Библиотеки CUDA найдены: распознавание работает на видеокарте NVIDIA."), "ok")
        elif offer == "old_driver":
            self._set_row(
                label,
                tr("Драйвер NVIDIA слишком старый для CUDA 12. Обновите драйвер, чтобы распознавать на видеокарте."),
                "warn",
            )
        elif offer == "download":
            self._set_row(
                label,
                tr(
                    "На видеокарте NVIDIA распознавание намного быстрее. Нужны библиотеки CUDA "
                    "(cuDNN и cuBLAS): до ~1,2 ГБ загрузки, ~1,8 ГБ на диске. Без них — на процессоре."
                ),
            )

    def _on_gpu_clicked(self) -> None:
        if self._gpu_worker is not None:
            self._gpu_worker.cancel.set()
            return
        self._btn_gpu.setText(tr("Отмена"))
        self._gpu_stage = "cuDNN"
        self._set_row(self._gpu_status, tr("⏳ Скачивание библиотек CUDA…"))
        self._gpu_worker = SpeechCudaDownloadWorker(self)
        self._gpu_worker.stage_changed.connect(lambda stage: setattr(self, "_gpu_stage", stage))
        self._gpu_worker.progress_changed.connect(
            lambda pct, done, total: self._set_row(
                self._gpu_status,
                tr(
                    "⏳ Скачивание {name}: {done} / {total} МБ ({pct}%)",
                    name=self._gpu_stage,
                    done=done,
                    total=total,
                    pct=pct,
                ),
            )
        )
        self._gpu_worker.finished_with_status.connect(self._on_gpu_done)
        self._gpu_worker.start()

    def _on_gpu_done(self, ok: bool, result: str) -> None:
        self._gpu_worker = None
        self._refresh_gpu_row()
        if not ok:
            self._set_row(
                self._gpu_status,
                tr("⚠ Не удалось скачать библиотеки CUDA: {error}", error=result)
                if result
                else tr("Скачивание отменено."),
                "warn" if result else "muted",
            )
