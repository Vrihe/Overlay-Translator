"""
ui/main_window.py — Main application window with a navigation rail.

Tabs:
  1. Главная    — status chips + text translation + screenshot (file / drag-and-drop)
                  OCR translation + the latest history records
  2. Настройки  — embedded SettingsWidget
  3. История    — embedded HistoryWidget
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFileDialog, QStackedWidget,
    QFrame, QComboBox, QBoxLayout, QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

import logging
import os
import webbrowser
from datetime import datetime

import config
from i18n import tr
from tray.icon_gen import create_tray_icon
from ui import icons, theme
from ui.hud_widgets import Chip, FieldLabel, NavButton, Panel, page_title


# ── Background worker for update checking ────────────────

class _UpdateCheckWorker(QThread):
    """Worker to check for app updates in background."""
    update_done = pyqtSignal(bool, str, str)  # (has_update, version, url)

    def run(self):
        try:
            from updater.check_update import check_for_update
            has_update, version, url = check_for_update()
            self.update_done.emit(has_update, version, url)
        except Exception:
            self.update_done.emit(False, "", "")


# ── Background worker for text / image translation ───────

class _TextTranslateWorker(QThread):
    """Translate plain text on a background thread."""
    text_done = pyqtSignal(str, str)  # (translated_text, error_message)

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def run(self):
        logging.debug("TextTranslateWorker %#x: run() started", id(self))
        try:
            from translate.backend import translate
            result = translate(self._text, domain_id=config.ACTIVE_DOMAIN)
            self.text_done.emit(result, "")
        except Exception as e:
            logging.exception("TextTranslateWorker %#x: translation failed", id(self))
            self.text_done.emit("", str(e))
        logging.debug("TextTranslateWorker %#x: run() returning", id(self))


class _ImageTranslateWorker(QThread):
    """OCR + translate an image file on a background thread."""
    image_done = pyqtSignal(str, str, str)  # (source_text, translated_text, error)

    def __init__(self, filepath: str):
        super().__init__()
        self._path = filepath

    def run(self):
        try:
            from PIL import Image
            img = Image.open(self._path)
        except Exception as e:
            self.image_done.emit("", "", tr("Ошибка загрузки изображения:\n{error}", error=e))
            return

        try:
            from ocr.engine import recognise
            text = recognise(img)
        except Exception as e:
            self.image_done.emit("", "", tr("Ошибка OCR:\n{error}", error=e))
            return

        if not text:
            self.image_done.emit("", "", tr("Текст не распознан на изображении."))
            return

        try:
            from translate.backend import translate
            translated = translate(text, domain_id=config.ACTIVE_DOMAIN)
        except Exception as e:
            self.image_done.emit(text, "", tr("Ошибка перевода:\n{error}", error=e))
            return

        self.image_done.emit(text, translated, "")


class _ElidedLabel(QLabel):
    """Single-line plain-text label that elides with "…" to its current width."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full = text
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setText(text)

    def resizeEvent(self, event):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(event.size().width(), 10)))
        super().resizeEvent(event)


# ── Screenshot drop zone ─────────────────────────────────

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class _DropZone(QFrame):
    """Dashed area accepting a dropped image file; holds the upload button."""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._set_highlight(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 16)
        lay.setSpacing(8)

        p = theme.current()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("upload", p.accent, 26))
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(icon_lbl)

        cap = QLabel(tr("Перетащите скриншот сюда"))
        cap.setAlignment(Qt.AlignCenter)
        cap.setWordWrap(True)
        cap.setStyleSheet(theme.text_css(p.text_soft, 9.5) + " border: none;")
        lay.addWidget(cap)

        formats = QLabel("PNG · JPG · BMP · WEBP")
        formats.setAlignment(Qt.AlignCenter)
        formats.setFont(theme.body_font(8, spacing=110))
        formats.setStyleSheet(f"color: {p.muted}; background: transparent; border: none;")
        lay.addWidget(formats)

        self.button = QPushButton(tr("Загрузить скриншот").upper())
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setStyleSheet(theme.btn_accent("7px 14px", 8.5))
        lay.addSpacing(4)
        lay.addWidget(self.button, 0, Qt.AlignHCenter)

    def _set_highlight(self, on: bool) -> None:
        p = theme.current()
        self.setStyleSheet(
            f"#dropZone {{ border: 1px dashed {p.accent if on else p.dim};"
            f" background: {p.tint if on else 'transparent'}; }}"
        )

    @staticmethod
    def _image_path(event) -> str | None:
        md = event.mimeData()
        if not md.hasUrls():
            return None
        for url in md.urls():
            path = url.toLocalFile()
            if path and os.path.splitext(path)[1].lower() in _IMAGE_EXTS:
                return path
        return None

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._image_path(event):
            event.acceptProposedAction()
            self._set_highlight(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_highlight(False)
        path = self._image_path(event)
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)


# ── Home page ────────────────────────────────────────────

class _HomePage(QWidget):
    """Home tab: status chips + text translation + screenshot translation + recent."""

    # Below this width the two columns stack vertically.
    _STACK_BELOW = 760
    _RECENT_LIMIT = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_worker: _TextTranslateWorker | None = None
        self._image_worker: _ImageTranslateWorker | None = None
        self._build_ui()

    def _build_ui(self):
        p = theme.current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # ── Header: title + status chips ─────────────────
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(page_title(tr("Главная")))
        header.addStretch()

        self._status_chip = Chip(tr("Онлайн"), "ok")
        header.addWidget(self._status_chip)
        self._lang_lbl = Chip(kind="neutral")
        header.addWidget(self._lang_lbl)
        self._hotkey_lbl = Chip(kind="accent")
        header.addWidget(self._hotkey_lbl)
        layout.addLayout(header)

        # ── Body: two columns (stack on narrow windows) ──
        self._columns = QBoxLayout(QBoxLayout.LeftToRight)
        self._columns.setSpacing(16)
        layout.addLayout(self._columns, 1)

        # Left: text translation panel
        text_panel = Panel(tr("Перевод текста"))
        self._domain_combo = QComboBox()
        self._domain_combo.setStyleSheet(theme.combo_css(9))
        self._domain_combo.setToolTip(tr("Контекст перевода:"))
        self._domain_combo.setMinimumWidth(150)
        self._domain_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        from translate.domain_manager import list_available_domains
        for d in list_available_domains():
            self._domain_combo.addItem(f"{d['display_name']} ({d['id']})", d["id"])

        idx_dom = self._domain_combo.findData(config.ACTIVE_DOMAIN)
        if idx_dom >= 0:
            self._domain_combo.setCurrentIndex(idx_dom)

        self._domain_combo.currentIndexChanged.connect(self._on_domain_changed)
        text_panel.header.addWidget(self._domain_combo)

        text_panel.body.addWidget(FieldLabel(tr("Ввод"), prompt=True))
        self._text_input = QTextEdit()
        self._text_input.setPlaceholderText(tr("Введите или вставьте текст для перевода…"))
        self._text_input.setStyleSheet(theme.input_css(10, "8px 10px"))
        self._text_input.setFixedHeight(84)
        text_panel.body.addWidget(self._text_input)

        self._btn_translate = QPushButton(tr("Перевести").upper())
        self._btn_translate.setCursor(Qt.PointingHandCursor)
        self._btn_translate.setFont(theme.display_font(10, spacing=112))
        self._btn_translate.setStyleSheet(theme.btn_primary("9px 22px", 10))
        self._btn_translate.clicked.connect(self._on_translate_text)
        text_panel.body.addWidget(self._btn_translate)

        self._result_caption = FieldLabel(tr("Результат"), prompt=True, accent=True)
        text_panel.body.addWidget(self._result_caption)

        # Error / status line (plain text: shows provider error text).
        self._result_label = QLabel("")
        self._result_label.setTextFormat(Qt.PlainText)
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet(theme.label_css("muted"))
        self._result_label.setVisible(False)
        text_panel.body.addWidget(self._result_label)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setPlaceholderText(tr("Перевод появится здесь"))
        self._result_text.setStyleSheet(theme.result_css())
        self._result_text.setMinimumHeight(70)
        text_panel.body.addWidget(self._result_text, 1)

        self._columns.addWidget(text_panel, 135)

        # Right column: screenshot panel + recent panel
        right = QVBoxLayout()
        right.setSpacing(16)

        img_panel = Panel(tr("Из скриншота"))
        self._drop_zone = _DropZone()
        self._drop_zone.file_dropped.connect(self._start_image_translation)
        self._btn_load_image = self._drop_zone.button
        self._btn_load_image.clicked.connect(self._on_load_image)
        img_panel.body.addWidget(self._drop_zone)

        self._img_result_label = QLabel("")
        self._img_result_label.setTextFormat(Qt.PlainText)
        self._img_result_label.setWordWrap(True)
        self._img_result_label.setStyleSheet(theme.label_css("muted"))
        self._img_result_label.setVisible(False)
        img_panel.body.addWidget(self._img_result_label)

        self._img_source_text = QTextEdit()
        self._img_source_text.setReadOnly(True)
        self._img_source_text.setStyleSheet(theme.input_css(9, "6px 8px"))
        self._img_source_text.setVisible(False)
        self._img_source_text.setFixedHeight(60)
        img_panel.body.addWidget(self._img_source_text)

        self._img_result_text = QTextEdit()
        self._img_result_text.setReadOnly(True)
        self._img_result_text.setStyleSheet(theme.result_css(10))
        self._img_result_text.setVisible(False)
        self._img_result_text.setMinimumHeight(60)
        img_panel.body.addWidget(self._img_result_text)
        right.addWidget(img_panel)

        recent_panel = Panel(tr("Последние"))
        self._recent_layout = QVBoxLayout()
        self._recent_layout.setSpacing(0)
        recent_panel.body.addLayout(self._recent_layout)
        recent_panel.body.addStretch()
        right.addWidget(recent_panel, 1)

        self._columns.addLayout(right, 100)

        self.refresh_status()

    def resizeEvent(self, event):
        direction = (QBoxLayout.TopToBottom if event.size().width() < self._STACK_BELOW
                     else QBoxLayout.LeftToRight)
        if self._columns.direction() != direction:
            self._columns.setDirection(direction)
        super().resizeEvent(event)

    # ── Domain change ────────────────────────────────────

    def _on_domain_changed(self):
        new_domain = self._domain_combo.currentData()
        if new_domain:
            config.ACTIVE_DOMAIN = new_domain

    # ── Status refresh ───────────────────────────────────

    def refresh_status(self):
        """Update status chips and the recent list to reflect current config / history."""
        self._hotkey_lbl.set_chip_text(config.HOTKEY.upper())
        self._lang_lbl.set_chip_text(
            tr("{src} → {tgt}", src=config.SOURCE_LANG.upper(), tgt=config.TARGET_LANG.upper())
        )
        idx = self._domain_combo.findData(config.ACTIVE_DOMAIN)
        if idx >= 0 and self._domain_combo.currentIndex() != idx:
            self._domain_combo.blockSignals(True)
            self._domain_combo.setCurrentIndex(idx)
            self._domain_combo.blockSignals(False)
        self.refresh_recent()

    def refresh_recent(self):
        """Show the newest history records (read through cache/store, never logged)."""
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

        try:
            import cache.store as store
            records = store.get_all_history(limit=self._RECENT_LIMIT)
        except Exception:
            logging.exception("Failed to read recent history")
            records = []

        p = theme.current()
        if not records:
            empty = QLabel(tr("Пока нет переводов"))
            empty.setStyleSheet(theme.label_css("muted"))
            self._recent_layout.addWidget(empty)
            return

        for i, rec in enumerate(records):
            row = QFrame()
            row.setObjectName("recentRow")
            border = f"border-top: 1px solid {p.line};" if i else "border: none;"
            row.setStyleSheet(f"#recentRow {{ background: transparent; {border} }}")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 8, 0, 8)
            rl.setSpacing(3)

            ts = rec.get("timestamp", 0)
            when = datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "—"
            meta = QLabel(
                f"{rec.get('source_lang', '').upper()} → {rec.get('target_lang', '').upper()}"
                f"  ·  {when}"
            )
            meta.setFont(theme.body_font(7.5, spacing=110))
            meta.setStyleSheet(f"color: {p.muted}; background: transparent;")
            rl.addWidget(meta)

            text = " ".join(str(rec.get("translated_text", "")).split())
            body = _ElidedLabel(text)
            body.setStyleSheet(theme.text_css(p.text, 9))
            body.setToolTip(text[:500])
            rl.addWidget(body)
            self._recent_layout.addWidget(row)

    # ── Text translation ─────────────────────────────────

    def _on_translate_text(self):
        text = self._text_input.toPlainText().strip()
        if not text:
            return

        self._btn_translate.setEnabled(False)
        self._btn_translate.setText(tr("Переводим…").upper())
        self._result_label.setText("")
        self._result_label.setVisible(False)

        self._text_worker = _TextTranslateWorker(text)
        self._text_worker.text_done.connect(self._on_text_translated)
        self._text_worker.start()

    def _on_text_translated(self, translated: str, error: str):
        try:
            self._show_text_translation(translated, error)
        except Exception:
            logging.exception("Failed to show text translation result")

    def _show_text_translation(self, translated: str, error: str):
        worker = self._text_worker
        # Diagnostic: dropping the last reference to a QThread that is still
        # running makes Qt abort the whole process (qFatal).
        logging.debug(
            "Text translation result received | worker=%s | still running=%s",
            f"{id(worker):#x}" if worker is not None else None,
            worker.isRunning() if worker is not None else None,
        )
        self._text_worker = None
        self._btn_translate.setEnabled(True)
        self._btn_translate.setText(tr("Перевести").upper())

        if error:
            self._result_label.setText(tr("Ошибка: {error}", error=error))
            self._result_label.setStyleSheet(theme.label_css("error"))
            self._result_label.setVisible(True)
            self._result_text.clear()
        else:
            self._result_label.setVisible(False)
            self._result_text.setPlainText(translated)
            self.refresh_recent()

    # ── Image translation ────────────────────────────────

    def _on_load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Выберите изображение"),
            "",
            tr("Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.webp);;Все файлы (*)"),
        )
        if not path:
            return
        self._start_image_translation(path)

    def _start_image_translation(self, path: str):
        if self._image_worker is not None:
            return  # one image at a time (also guards against a drop mid-run)

        self._btn_load_image.setEnabled(False)
        self._drop_zone.setEnabled(False)
        self._btn_load_image.setText(tr("Обрабатываем…").upper())
        self._img_result_label.setVisible(False)
        self._img_source_text.setVisible(False)
        self._img_result_text.setVisible(False)

        self._image_worker = _ImageTranslateWorker(path)
        self._image_worker.image_done.connect(self._on_image_translated)
        self._image_worker.start()

    def _on_image_translated(self, source: str, translated: str, error: str):
        self._image_worker = None
        self._btn_load_image.setEnabled(True)
        self._drop_zone.setEnabled(True)
        self._btn_load_image.setText(tr("Загрузить скриншот").upper())

        if error:
            self._img_result_label.setText(error)
            self._img_result_label.setStyleSheet(theme.label_css("error"))
            self._img_result_label.setVisible(True)
            self._img_source_text.setVisible(False)
            self._img_result_text.setVisible(False)
        else:
            self._img_result_label.setText(tr("✓ Текст распознан и переведён:"))
            self._img_result_label.setStyleSheet(theme.label_css("ok"))
            self._img_result_label.setVisible(True)

            if source:
                self._img_source_text.setPlainText(source)
                self._img_source_text.setVisible(True)

            self._img_result_text.setPlainText(translated)
            self._img_result_text.setVisible(True)
            self.refresh_recent()


# ── Main Window ──────────────────────────────────────────

class MainWindow(QMainWindow):
    """Main application window with a navigation rail."""

    _RAIL_WIDTH = 72

    # Page indices
    PAGE_HOME = 0
    PAGE_SETTINGS = 1
    PAGE_HISTORY = 2

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Translator Overlay")
        self.setWindowIcon(create_tray_icon())
        self.resize(920, 620)
        self.setMinimumSize(700, 450)

        p = theme.current()
        self.setStyleSheet(f"QMainWindow {{ background: {p.bg}; }}" + theme.scrollbar_css())

        self._tray_icon = None
        self._update_worker = None

        self._build_ui()
        self._connect_signals()
        self.switch_to_page(self.PAGE_HOME)

        # Check for updates in background on launch
        self._start_update_check()

    def set_tray_icon(self, tray_icon):
        """Pass system tray icon reference to MainWindow for notifications."""
        self._tray_icon = tray_icon

    def _start_update_check(self):
        """Launch background thread to check for updates."""
        self._update_worker = _UpdateCheckWorker()
        self._update_worker.update_done.connect(self._on_update_check_finished)
        self._update_worker.start()

    def _on_update_check_finished(self, has_update: bool, version: str, url: str):
        self._update_worker = None
        if has_update and url:
            self._update_label.setText(tr("Доступно обновление {version}", version=version).upper())
            self._update_banner.setVisible(True)
            try:
                self._btn_download_update.clicked.disconnect()
            except Exception:
                pass
            self._btn_download_update.clicked.connect(lambda: webbrowser.open(url))

            if hasattr(self, "_tray_icon") and self._tray_icon and hasattr(self._tray_icon, "showMessage"):
                try:
                    from PyQt5.QtWidgets import QSystemTrayIcon
                    self._tray_icon.showMessage(
                        tr("Доступно обновление"),
                        tr(
                            "Вышла новая версия {version}. Нажмите, чтобы открыть страницу скачивания.",
                            version=version,
                        ),
                        QSystemTrayIcon.Information,
                        8000,
                    )
                    self._tray_icon.messageClicked.connect(lambda: webbrowser.open(url))
                except Exception:
                    pass

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self):
        p = theme.current()
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Navigation rail ──────────────────────────────
        rail = QFrame()
        rail.setObjectName("navRail")
        rail.setFixedWidth(self._RAIL_WIDTH)
        rail.setStyleSheet(
            f"#navRail {{ background: {p.rail}; border: none; border-right: 1px solid {p.line}; }}"
        )

        sb_layout = QVBoxLayout(rail)
        sb_layout.setContentsMargins(0, 16, 0, 16)
        sb_layout.setSpacing(6)
        sb_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Logo tile
        logo = QLabel("T")
        logo.setFixedSize(38, 38)
        logo.setAlignment(Qt.AlignCenter)
        logo_font = theme.display_font(17, spacing=100)
        logo_font.setWeight(QFont.Bold)
        logo.setFont(logo_font)
        logo.setToolTip(f"Translator Overlay v{getattr(config, 'APP_VERSION', '1.0.0')}")
        logo.setStyleSheet(f"background: {p.accent}; color: {p.on_accent};")
        sb_layout.addWidget(logo, 0, Qt.AlignHCenter)
        sb_layout.addSpacing(14)

        # Navigation buttons
        self._btn_home = NavButton("home", tr("Главная"))
        self._btn_settings = NavButton("sliders", tr("Опции"))
        self._btn_history = NavButton("clock", tr("История"))

        self._nav_buttons = [self._btn_home, self._btn_settings, self._btn_history]

        for btn in self._nav_buttons:
            sb_layout.addWidget(btn, 0, Qt.AlignHCenter)

        sb_layout.addStretch()
        root.addWidget(rail)

        # ── Right content container (Banner + Stack) ─────
        right_container = QWidget()
        right_container.setObjectName("rightContainer")
        # Rules on page ancestors are selector-scoped: unscoped ones cascade into the
        # QMessageBox / QInputDialog opened from a page and override ui/theme.py.
        right_container.setStyleSheet(f"#rightContainer {{ background: {p.bg}; }}")
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Update banner (hidden by default)
        self._update_banner = QFrame()
        self._update_banner.setObjectName("updateBanner")
        self._update_banner.setStyleSheet(
            f"#updateBanner {{ background: {p.panel}; border: none;"
            f" border-bottom: 1px solid {p.accent}; }}"
        )
        ub_layout = QHBoxLayout(self._update_banner)
        ub_layout.setContentsMargins(20, 8, 20, 8)

        self._update_label = QLabel("")
        self._update_label.setTextFormat(Qt.PlainText)  # version comes from GitHub
        self._update_label.setFont(theme.body_font(8.5, medium=True, spacing=110))
        self._update_label.setStyleSheet(f"color: {p.text}; background: transparent;")
        ub_layout.addWidget(self._update_label)
        ub_layout.addStretch()

        self._btn_download_update = QPushButton(tr("Скачать обновление").upper())
        self._btn_download_update.setCursor(Qt.PointingHandCursor)
        self._btn_download_update.setStyleSheet(theme.btn_accent("5px 14px", 8.5))
        ub_layout.addWidget(self._btn_download_update)
        self._update_banner.setVisible(False)
        right_layout.addWidget(self._update_banner)

        # ── Content area (QStackedWidget) ────────────────
        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")
        self._stack.setStyleSheet(f"#pageStack {{ background: {p.bg}; }}")

        # Page 0: Home
        home_scroll = QScrollArea()
        home_scroll.setWidgetResizable(True)
        home_scroll.setFrameShape(QFrame.NoFrame)
        home_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._home_page = _HomePage()
        self._home_page.setObjectName("homePage")
        self._home_page.setStyleSheet("#homePage { background: transparent; }")
        home_scroll.setWidget(self._home_page)
        self._stack.addWidget(home_scroll)

        # Page 1: Settings (lazy-loaded)
        self._settings_placeholder = QWidget()
        self._settings_placeholder.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._settings_placeholder)
        self._settings_widget = None

        # Page 2: History (lazy-loaded)
        self._history_placeholder = QWidget()
        self._history_placeholder.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._history_placeholder)
        self._history_widget = None

        right_layout.addWidget(self._stack, 1)
        root.addWidget(right_container, 1)

    # ── Signals ──────────────────────────────────────────

    def _connect_signals(self):
        self._btn_home.clicked.connect(lambda: self.switch_to_page(self.PAGE_HOME))
        self._btn_settings.clicked.connect(lambda: self.switch_to_page(self.PAGE_SETTINGS))
        self._btn_history.clicked.connect(lambda: self.switch_to_page(self.PAGE_HISTORY))

    # ── Page switching ───────────────────────────────────

    def switch_to_page(self, index: int):
        """Switch the stacked widget to the given page index."""
        # Lazy-load settings widget
        if index == self.PAGE_SETTINGS and self._settings_widget is None:
            self._init_settings_page()

        # Lazy-load history widget
        if index == self.PAGE_HISTORY and self._history_widget is None:
            self._init_history_page()

        # Refresh data when switching
        if index == self.PAGE_HOME:
            self._home_page.refresh_status()
        elif index == self.PAGE_SETTINGS and self._settings_widget is not None:
            self._settings_widget.reload()
        elif index == self.PAGE_HISTORY and self._history_widget is not None:
            self._history_widget.reload()

        self._stack.setCurrentIndex(index)

        # Update sidebar button states
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)

    def _init_settings_page(self):
        """Lazy-init the settings page with SettingsWidget (it scrolls its own sections)."""
        try:
            from ui.settings_dialog import SettingsWidget
            settings_widget = SettingsWidget()
        except Exception:
            logging.exception("Failed to initialize settings page")
            return

        container = QWidget()
        container.setObjectName("settingsPage")
        container.setStyleSheet("#settingsPage { background: transparent; }")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(24, 20, 24, 16)
        title_row.addWidget(page_title(tr("Настройки")))
        title_row.addStretch()
        vbox.addLayout(title_row)

        self._settings_widget = settings_widget
        # C2: keep tray language checkmarks in sync when settings are saved
        if getattr(self, "_tray_icon", None) is not None and hasattr(self._tray_icon, "rebuild_lang_menu"):
            self._settings_widget.settings_saved.connect(self._tray_icon.rebuild_lang_menu)
        self._settings_widget.settings_saved.connect(self._home_page.refresh_status)
        vbox.addWidget(self._settings_widget, 1)

        self._stack.removeWidget(self._settings_placeholder)
        self._settings_placeholder.deleteLater()
        self._stack.insertWidget(self.PAGE_SETTINGS, container)

    def _init_history_page(self):
        """Lazy-init the history page with HistoryWidget (it has its own title row)."""
        try:
            from history.history_window import HistoryWidget
            history_widget = HistoryWidget()
        except Exception:
            logging.exception("Failed to initialize history page")
            return

        container = QWidget()
        container.setObjectName("historyPage")
        container.setStyleSheet("#historyPage { background: transparent; }")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(24, 20, 24, 20)
        vbox.setSpacing(0)

        self._history_widget = history_widget
        vbox.addWidget(self._history_widget, 1)

        self._stack.removeWidget(self._history_placeholder)
        self._history_placeholder.deleteLater()
        self._stack.insertWidget(self.PAGE_HISTORY, container)

    # ── Show / restore ───────────────────────────────────

    def toggle_visibility(self):
        """Toggle window visibility (for tray icon click)."""
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show()
            self.setWindowState(
                self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
            )
            self.raise_()
            self.activateWindow()

    def show_window(self):
        """Show, restore and focus the window (e.g. on a repeated app launch)."""
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
        )
        self.raise_()
        self.activateWindow()

    def show_and_switch(self, page_index: int):
        """Show the window and switch to a specific tab."""
        self.show_window()
        self.switch_to_page(page_index)

    # ── Close event → hide to tray ───────────────────────

    def closeEvent(self, event):
        """Override close: hide to tray instead of quitting."""
        event.ignore()
        self.hide()
