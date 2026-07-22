"""
ui/main_window.py — Main application window with sidebar navigation.

Tabs:
  1. Главная    — status overview + text translation + file-based OCR translation
  2. Настройки  — embedded SettingsWidget
  3. История    — embedded HistoryWidget
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFileDialog, QStackedWidget,
    QApplication, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QFont, QIcon

import config
from tray.icon_gen import create_tray_icon


# ── Background worker for text / image translation ───────

class _TextTranslateWorker(QThread):
    """Translate plain text on a background thread."""
    finished = pyqtSignal(str, str)  # (translated_text, error_message)

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def run(self):
        try:
            from translate.llm_client import translate
            result = translate(self._text)
            self.finished.emit(result, "")
        except Exception as e:
            self.finished.emit("", str(e))


class _ImageTranslateWorker(QThread):
    """OCR + translate an image file on a background thread."""
    finished = pyqtSignal(str, str, str)  # (source_text, translated_text, error)

    def __init__(self, filepath: str):
        super().__init__()
        self._path = filepath

    def run(self):
        try:
            from PIL import Image
            img = Image.open(self._path)
        except Exception as e:
            self.finished.emit("", "", f"Ошибка загрузки изображения:\n{e}")
            return

        try:
            from ocr.engine import recognise
            text = recognise(img)
        except Exception as e:
            self.finished.emit("", "", f"Ошибка OCR:\n{e}")
            return

        if not text:
            self.finished.emit("", "", "Текст не распознан на изображении.")
            return

        try:
            from translate.llm_client import translate
            translated = translate(text)
        except Exception as e:
            self.finished.emit(text, "", f"Ошибка перевода:\n{e}")
            return

        self.finished.emit(text, translated, "")


# ── Sidebar button ───────────────────────────────────────

class _SidebarButton(QPushButton):
    """Custom sidebar navigation button."""

    def __init__(self, icon_text: str, label: str, parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_text}  {label}")
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self._style(False))

    @staticmethod
    def _style(active: bool) -> str:
        if active:
            return (
                "QPushButton {"
                "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                "    stop:0 rgba(91,141,239,0.25), stop:1 rgba(91,141,239,0.08));"
                "  color: #ffffff; border: none; border-left: 3px solid #5b8def;"
                "  border-radius: 0; padding: 0 16px;"
                "  font-family: 'Segoe UI'; font-size: 10.5pt; font-weight: 600;"
                "  text-align: left;"
                "}"
            )
        return (
            "QPushButton {"
            "  background: transparent; color: #8888aa; border: none;"
            "  border-left: 3px solid transparent;"
            "  border-radius: 0; padding: 0 16px;"
            "  font-family: 'Segoe UI'; font-size: 10.5pt; font-weight: 500;"
            "  text-align: left;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(255,255,255,0.04); color: #b0b0cc;"
            "}"
        )

    def set_active(self, active: bool):
        self.setChecked(active)
        self.setStyleSheet(self._style(active))


# ── Home page ────────────────────────────────────────────

class _HomePage(QWidget):
    """Home tab: status + text translation + image file translation."""

    _CSS_LABEL = "font-family: 'Segoe UI'; color: #ccc; font-size: 10pt; background: transparent;"
    _CSS_TITLE = "font-family: 'Segoe UI'; color: #e8e8e8; font-size: 13pt; font-weight: 600; background: transparent;"
    _CSS_MUTED = "font-family: 'Segoe UI'; color: #888; font-size: 9.5pt; background: transparent;"

    _INPUT_CSS = (
        "QTextEdit {"
        "  background: #232334; color: #e0e0e0; border: 1px solid #3a3a4e;"
        "  border-radius: 8px; padding: 10px;"
        "  font-family: 'Segoe UI'; font-size: 10.5pt;"
        "}"
        "QTextEdit:focus {"
        "  border-color: #5b8def;"
        "}"
    )

    _RESULT_CSS = (
        "QTextEdit {"
        "  background: #1a1a2e; color: #e0e0e0; border: 1px solid #2a2a40;"
        "  border-radius: 8px; padding: 10px;"
        "  font-family: 'Segoe UI'; font-size: 10.5pt;"
        "}"
    )

    _BTN_PRIMARY = (
        "QPushButton {"
        "  background: #5b8def; color: #fff; border: none;"
        "  border-radius: 6px; padding: 9px 24px;"
        "  font-family: 'Segoe UI'; font-size: 10pt; font-weight: 600;"
        "}"
        "QPushButton:hover { background: #4a7de0; }"
        "QPushButton:disabled { background: #3a3a5c; color: #666; }"
    )

    _BTN_SECONDARY = (
        "QPushButton {"
        "  background: transparent; color: #aaa; border: 1px solid #444;"
        "  border-radius: 6px; padding: 9px 24px;"
        "  font-family: 'Segoe UI'; font-size: 10pt;"
        "}"
        "QPushButton:hover { background: #2a2a3e; color: #ccc; }"
        "QPushButton:disabled { background: #1a1a28; color: #555; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_worker: _TextTranslateWorker | None = None
        self._image_worker: _ImageTranslateWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # ── Status card ──────────────────────────────────
        status_card = QFrame()
        status_card.setStyleSheet(
            "QFrame {"
            "  background: #1e1e30; border: 1px solid #2a2a40;"
            "  border-radius: 10px;"
            "}"
        )
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(18, 14, 18, 14)
        sc_layout.setSpacing(8)

        # Status row
        status_row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: #4ade80; font-size: 10pt; background: transparent;")
        dot.setFixedWidth(18)
        status_row.addWidget(dot)
        status_lbl = QLabel("Приложение запущено")
        status_lbl.setStyleSheet(self._CSS_LABEL + " font-weight: 600;")
        status_row.addWidget(status_lbl)
        status_row.addStretch()
        sc_layout.addLayout(status_row)

        # Info row
        info_row = QHBoxLayout()
        info_row.setSpacing(24)

        self._hotkey_lbl = QLabel(f"⌨ Хоткей:  {config.HOTKEY.upper()}")
        self._hotkey_lbl.setStyleSheet(self._CSS_MUTED)
        info_row.addWidget(self._hotkey_lbl)

        self._lang_lbl = QLabel(
            f"🌍 Перевод:  {config.SOURCE_LANG.upper()} → {config.TARGET_LANG.upper()}"
        )
        self._lang_lbl.setStyleSheet(self._CSS_MUTED)
        info_row.addWidget(self._lang_lbl)
        info_row.addStretch()
        sc_layout.addLayout(info_row)

        layout.addWidget(status_card)

        # ── Text translation section ─────────────────────
        txt_title = QLabel("📝 Перевод текста")
        txt_title.setStyleSheet(self._CSS_TITLE)
        layout.addWidget(txt_title)

        self._text_input = QTextEdit()
        self._text_input.setPlaceholderText("Введите или вставьте текст для перевода…")
        self._text_input.setStyleSheet(self._INPUT_CSS)
        self._text_input.setFixedHeight(100)
        layout.addWidget(self._text_input)

        btn_row = QHBoxLayout()
        self._btn_translate = QPushButton("Перевести")
        self._btn_translate.setStyleSheet(self._BTN_PRIMARY)
        self._btn_translate.clicked.connect(self._on_translate_text)
        btn_row.addWidget(self._btn_translate)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Result area ──────────────────────────────────
        self._result_label = QLabel("")
        self._result_label.setStyleSheet(self._CSS_MUTED)
        self._result_label.setVisible(False)
        layout.addWidget(self._result_label)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setStyleSheet(self._RESULT_CSS)
        self._result_text.setVisible(False)
        self._result_text.setMinimumHeight(60)
        layout.addWidget(self._result_text)

        # ── Separator ────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #2a2a40; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # ── Image translation section ────────────────────
        img_title = QLabel("🖼 Перевод из файла")
        img_title.setStyleSheet(self._CSS_TITLE)
        layout.addWidget(img_title)

        img_desc = QLabel("Загрузите скриншот — текст будет распознан через OCR и переведён")
        img_desc.setStyleSheet(self._CSS_MUTED)
        img_desc.setWordWrap(True)
        layout.addWidget(img_desc)

        img_btn_row = QHBoxLayout()
        self._btn_load_image = QPushButton("📁 Загрузить скриншот")
        self._btn_load_image.setStyleSheet(self._BTN_SECONDARY)
        self._btn_load_image.clicked.connect(self._on_load_image)
        img_btn_row.addWidget(self._btn_load_image)
        img_btn_row.addStretch()
        layout.addLayout(img_btn_row)

        self._img_result_label = QLabel("")
        self._img_result_label.setStyleSheet(self._CSS_MUTED)
        self._img_result_label.setVisible(False)
        layout.addWidget(self._img_result_label)

        self._img_source_text = QTextEdit()
        self._img_source_text.setReadOnly(True)
        self._img_source_text.setStyleSheet(self._RESULT_CSS)
        self._img_source_text.setVisible(False)
        self._img_source_text.setFixedHeight(60)
        layout.addWidget(self._img_source_text)

        self._img_result_text = QTextEdit()
        self._img_result_text.setReadOnly(True)
        self._img_result_text.setStyleSheet(self._RESULT_CSS)
        self._img_result_text.setVisible(False)
        self._img_result_text.setMinimumHeight(60)
        layout.addWidget(self._img_result_text)

        layout.addStretch()

    # ── Status refresh ───────────────────────────────────

    def refresh_status(self):
        """Update status labels to reflect current config."""
        self._hotkey_lbl.setText(f"⌨ Хоткей:  {config.HOTKEY.upper()}")
        self._lang_lbl.setText(
            f"🌍 Перевод:  {config.SOURCE_LANG.upper()} → {config.TARGET_LANG.upper()}"
        )

    # ── Text translation ─────────────────────────────────

    def _on_translate_text(self):
        text = self._text_input.toPlainText().strip()
        if not text:
            return

        self._btn_translate.setEnabled(False)
        self._btn_translate.setText("Переводим…")
        self._result_label.setText("")
        self._result_label.setVisible(False)
        self._result_text.setVisible(False)

        self._text_worker = _TextTranslateWorker(text)
        self._text_worker.finished.connect(self._on_text_translated)
        self._text_worker.start()

    def _on_text_translated(self, translated: str, error: str):
        self._text_worker = None
        self._btn_translate.setEnabled(True)
        self._btn_translate.setText("Перевести")

        if error:
            self._result_label.setText(f"❌ Ошибка: {error}")
            self._result_label.setStyleSheet(
                "font-family: 'Segoe UI'; color: #ff6b6b; font-size: 9.5pt; background: transparent;"
            )
            self._result_label.setVisible(True)
            self._result_text.setVisible(False)
        else:
            self._result_label.setText("✓ Результат перевода:")
            self._result_label.setStyleSheet(
                "font-family: 'Segoe UI'; color: #66cc99; font-size: 9.5pt; background: transparent;"
            )
            self._result_label.setVisible(True)
            self._result_text.setPlainText(translated)
            self._result_text.setVisible(True)

    # ── Image translation ────────────────────────────────

    def _on_load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.webp);;Все файлы (*)",
        )
        if not path:
            return

        self._btn_load_image.setEnabled(False)
        self._btn_load_image.setText("📁 Обрабатываем…")
        self._img_result_label.setVisible(False)
        self._img_source_text.setVisible(False)
        self._img_result_text.setVisible(False)

        self._image_worker = _ImageTranslateWorker(path)
        self._image_worker.finished.connect(self._on_image_translated)
        self._image_worker.start()

    def _on_image_translated(self, source: str, translated: str, error: str):
        self._image_worker = None
        self._btn_load_image.setEnabled(True)
        self._btn_load_image.setText("📁 Загрузить скриншот")

        if error:
            self._img_result_label.setText(f"❌ {error}")
            self._img_result_label.setStyleSheet(
                "font-family: 'Segoe UI'; color: #ff6b6b; font-size: 9.5pt;"
                " background: transparent;"
            )
            self._img_result_label.setVisible(True)
            self._img_source_text.setVisible(False)
            self._img_result_text.setVisible(False)
        else:
            self._img_result_label.setText("✓ Текст распознан и переведён:")
            self._img_result_label.setStyleSheet(
                "font-family: 'Segoe UI'; color: #66cc99; font-size: 9.5pt;"
                " background: transparent;"
            )
            self._img_result_label.setVisible(True)

            if source:
                self._img_source_text.setPlainText(source)
                self._img_source_text.setVisible(True)

            self._img_result_text.setPlainText(translated)
            self._img_result_text.setVisible(True)


# ── Main Window ──────────────────────────────────────────

class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    _SIDEBAR_WIDTH = 210

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

        self.setStyleSheet(
            "QMainWindow { background: #1c1c24; }"
            "QScrollBar:vertical {"
            "  background: transparent; width: 6px; margin: 0px; border-radius: 3px;"
            "}"
            "QScrollBar::handle:vertical {"
            "  background: rgba(255, 255, 255, 0.2); min-height: 20px; border-radius: 3px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            "  background: rgba(255, 255, 255, 0.35);"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            "  background: none; height: 0px;"
            "}"
        )

        self._build_ui()
        self._connect_signals()
        self.switch_to_page(self.PAGE_HOME)

    # ── Build UI ─────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(self._SIDEBAR_WIDTH)
        sidebar.setStyleSheet("background: #16162a;")

        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # Logo / app name
        logo_container = QWidget()
        logo_container.setFixedHeight(70)
        logo_container.setStyleSheet("background: transparent;")
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setContentsMargins(20, 16, 16, 8)

        app_name = QLabel("Translator Overlay")
        app_name.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 13pt; font-weight: 700;"
            " color: #e0e0f0; background: transparent;"
        )
        logo_layout.addWidget(app_name)

        ver_label = QLabel("v1.0")
        ver_label.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 8.5pt; color: #555570;"
            " background: transparent;"
        )
        logo_layout.addWidget(ver_label)

        sb_layout.addWidget(logo_container)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #2a2a40; border: none; max-height: 1px;")
        sb_layout.addWidget(sep)

        sb_layout.addSpacing(8)

        # Navigation buttons
        self._btn_home = _SidebarButton("🏠", "Главная")
        self._btn_settings = _SidebarButton("⚙️", "Настройки")
        self._btn_history = _SidebarButton("📜", "История")

        self._nav_buttons = [self._btn_home, self._btn_settings, self._btn_history]

        for btn in self._nav_buttons:
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Bottom info
        bottom_info = QLabel("  ⌨ " + config.HOTKEY.upper())
        bottom_info.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 8.5pt; color: #444460;"
            " background: transparent; padding: 12px;"
        )
        sb_layout.addWidget(bottom_info)

        root.addWidget(sidebar)

        # ── Content area (QStackedWidget) ────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #1c1c24;")

        # Page 0: Home
        from PyQt5.QtWidgets import QScrollArea
        home_scroll = QScrollArea()
        home_scroll.setWidgetResizable(True)
        home_scroll.setFrameShape(QFrame.NoFrame)
        home_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._home_page = _HomePage()
        self._home_page.setStyleSheet("background: transparent;")
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

        root.addWidget(self._stack, 1)

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
        """Lazy-init the settings page with SettingsWidget."""
        try:
            from ui.settings_dialog import SettingsWidget
        except ImportError:
            return

        from PyQt5.QtWidgets import QScrollArea

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(28, 24, 28, 24)
        vbox.setSpacing(0)

        title = QLabel("⚙️ Настройки")
        title.setStyleSheet(
            "font-family: 'Segoe UI'; color: #e8e8e8; font-size: 14pt;"
            " font-weight: 600; background: transparent; padding-bottom: 12px;"
        )
        vbox.addWidget(title)

        self._settings_widget = SettingsWidget()
        vbox.addWidget(self._settings_widget)
        vbox.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(container)

        self._stack.removeWidget(self._settings_placeholder)
        self._settings_placeholder.deleteLater()
        self._stack.insertWidget(self.PAGE_SETTINGS, scroll)

    def _init_history_page(self):
        """Lazy-init the history page with HistoryWidget."""
        try:
            from history.history_window import HistoryWidget
        except ImportError:
            return

        from PyQt5.QtWidgets import QScrollArea

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(28, 24, 28, 24)
        vbox.setSpacing(0)

        title = QLabel("📜 История переводов")
        title.setStyleSheet(
            "font-family: 'Segoe UI'; color: #e8e8e8; font-size: 14pt;"
            " font-weight: 600; background: transparent; padding-bottom: 12px;"
        )
        vbox.addWidget(title)

        self._history_widget = HistoryWidget()
        vbox.addWidget(self._history_widget, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(container)

        self._stack.removeWidget(self._history_placeholder)
        self._history_placeholder.deleteLater()
        self._stack.insertWidget(self.PAGE_HISTORY, scroll)

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

    def show_and_switch(self, page_index: int):
        """Show the window and switch to a specific tab."""
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
        )
        self.raise_()
        self.activateWindow()
        self.switch_to_page(page_index)

    # ── Close event → hide to tray ───────────────────────

    def closeEvent(self, event):
        """Override close: hide to tray instead of quitting."""
        event.ignore()
        self.hide()
