"""
Translator Overlay — entry point.

Full pipeline:
  Ctrl+Shift+R  →  region selector  →  screenshot (mss)
               →  OCR (EasyOCR)     →  translate (LLM)
               →  result popup

Main window is shown on startup with sidebar navigation.
System-tray icon runs in parallel for quick access.
"""

import ctypes
import os
import sys
import time
import traceback

# Pre-load PyTorch DLLs before PyQt5 to avoid Windows WinError 1114 DLL initialization failure
try:
    import torch
except Exception:
    pass

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, QRect, pyqtSignal, QThread
import keyboard

import config
import settings
from overlay.selector import RegionSelector
from capture.screenshot import capture_region
from ocr.engine import recognise
from translate.llm_client import translate, detect_and_translate
from translate.lang_detect import get_detector
from ui.result_popup import ResultPopup
from tray.tray_icon import TrayIcon
from ui.main_window import MainWindow


# ── Hide console window on Windows ───────────────────────

def _hide_console() -> None:
    """Hide the console window (only works when launched with python.exe)."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


# ── Bridge: keyboard thread → Qt main thread ─────────────

class HotkeyBridge(QObject):
    """Emits *triggered* from any thread; connected slot runs on the main thread."""
    triggered = pyqtSignal()


# ── Worker: Capture → OCR → Translate on background thread ──

class TranslationWorker(QThread):
    finished = pyqtSignal(str, str, str)  # (source_text, translated_text, error_message)

    def __init__(self, x1: int, y1: int, x2: int, y2: int):
        super().__init__()
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    def run(self):
        try:
            image = capture_region(self.x1, self.y1, self.x2, self.y2)
        except Exception as e:
            self.finished.emit("", "", f"Ошибка захвата экрана:\n{e}")
            return

        try:
            text = recognise(image)
        except Exception as e:
            self.finished.emit("", "", f"Ошибка OCR:\n{e}")
            return

        if not text:
            self.finished.emit("", "", "Текст не распознан.\nПопробуйте выделить область точнее.")
            return

        try:
            translated = translate(text)
        except Exception as e:
            self.finished.emit(text, "", f"Ошибка перевода:\n{e}\n\nРаспознанный текст:\n{text}")
            return

        self.finished.emit(text, translated, "")


# ── Application ──────────────────────────────────────────

class TranslatorApp:
    """Owns the QApplication, main window, tray icon, hotkey, selector, and result popups."""

    def __init__(self, app: QApplication):
        self.app = app
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("Translator Overlay")

        # ── Main window ─────────────────────────────────
        self._main_window = MainWindow()

        # ── System tray ──────────────────────────────────
        self._tray = TrayIcon()
        self._tray.act_show_window.triggered.connect(self._toggle_main_window)
        self._tray.act_translate.triggered.connect(self._show_selector)
        self._tray.act_settings.triggered.connect(
            lambda: self._main_window.show_and_switch(MainWindow.PAGE_SETTINGS)
        )
        self._tray.act_history.triggered.connect(
            lambda: self._main_window.show_and_switch(MainWindow.PAGE_HISTORY)
        )
        self._tray.act_exit.triggered.connect(self._quit)
        self._tray.show()

        # ── Show main window on startup ──────────────────
        self._main_window.show()

        # ── Hotkey bridges ───────────────────────────────
        self._bridge = HotkeyBridge()
        self._bridge.triggered.connect(self._show_selector)

        self._settings_bridge = HotkeyBridge()
        self._settings_bridge.triggered.connect(
            lambda: self._main_window.show_and_switch(MainWindow.PAGE_SETTINGS)
        )

        self._selector: RegionSelector | None = None
        self._popup: ResultPopup | None = None
        self._worker: TranslationWorker | None = None

        # Register global hotkeys (fire on a background thread).
        keyboard.add_hotkey(config.HOTKEY, self._bridge.triggered.emit)
        keyboard.add_hotkey(config.SETTINGS_HOTKEY, self._settings_bridge.triggered.emit)

    # ── Main window toggle ───────────────────────────────

    def _toggle_main_window(self) -> None:
        """Toggle main window visibility (for tray icon click)."""
        self._main_window.toggle_visibility()

    # ── Selector lifecycle ───────────────────────────────

    def _show_selector(self) -> None:
        """Create and show the region-selection overlay."""
        if self._selector is not None:
            return
        self._close_popup()

        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_cancelled)
        self._selector.destroyed.connect(self._on_selector_destroyed)
        self._selector.activate()

    def _on_cancelled(self) -> None:
        pass  # silent cancel, no console

    def _on_selector_destroyed(self) -> None:
        self._selector = None

    # ── Pipeline: capture → OCR → translate → popup ──────

    def _on_region_selected(self, x1: int, y1: int, x2: int, y2: int) -> None:
        anchor = QRect(x1, y1, x2 - x1, y2 - y1)

        # ── Step 0: Show loading popup immediately (only in popup mode) ──
        if config.NOTIFICATION_TYPE == "popup":
            self._close_popup()
            self._popup = ResultPopup(anchor=anchor, is_loading=True)
            self._popup.destroyed.connect(self._on_popup_destroyed)
            self._popup.show()
            QApplication.processEvents()

        # Stop previous background worker if running
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        # Start translation pipeline in background thread
        self._worker = TranslationWorker(x1, y1, x2, y2)
        self._worker.finished.connect(
            lambda src, tr, err: self._on_translation_finished(src, tr, err, anchor)
        )
        self._worker.start()

    def _on_translation_finished(self, source: str, translated: str, error_msg: str, anchor: QRect) -> None:
        self._worker = None
        if error_msg:
            self._show_error(error_msg, anchor)
        else:
            self._show_result(source, translated, anchor)

    # ── Popup helpers ────────────────────────────────────

    def _show_result(self, source: str, translated: str, anchor: QRect) -> None:
        from ui.result_popup import show_result
        self._popup = show_result(
            source,
            translated,
            anchor,
            is_error=False,
            tray_icon=self._tray,
            existing_popup=self._popup,
        )
        if self._popup is not None:
            self._popup.destroyed.connect(self._on_popup_destroyed)

    def _show_error(self, message: str, anchor: QRect) -> None:
        from ui.result_popup import show_result
        self._popup = show_result(
            "",
            message,
            anchor,
            is_error=True,
            tray_icon=self._tray,
            existing_popup=self._popup,
        )
        if self._popup is not None:
            self._popup.destroyed.connect(self._on_popup_destroyed)

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.hide()
                self._popup.deleteLater()
            except RuntimeError:
                pass
            self._popup = None

    def _on_popup_destroyed(self) -> None:
        self._popup = None

    # ── Quit ─────────────────────────────────────────────

    def _quit(self) -> None:
        """Full shutdown: unhook keyboard, close main window, hide tray, exit Qt loop."""
        keyboard.unhook_all()
        self._close_popup()
        # Force-close main window (bypass the hide-to-tray override)
        self._main_window.closeEvent = lambda e: e.accept()
        self._main_window.close()
        self._tray.hide()
        self.app.quit()

    # ── Run ──────────────────────────────────────────────

    def run(self) -> int:
        try:
            return self.app.exec_()
        except KeyboardInterrupt:
            self._quit()
            return 0


# ── API key check ────────────────────────────────────────

def _has_any_api_key() -> bool:
    """Return True if an API key is available from keyring or env vars."""
    return bool(
        settings.get_api_key("openrouter")
        or settings.get_api_key("anthropic")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


def main() -> None:
    _hide_console()

    app = QApplication(sys.argv)

    # ── First-run: ask for API key if none is configured ─
    if not _has_any_api_key():
        from ui.first_run_dialog import FirstRunDialog
        dlg = FirstRunDialog()
        if dlg.exec_() != FirstRunDialog.Accepted:
            sys.exit(0)

    translator = TranslatorApp(app)
    sys.exit(translator.run())


if __name__ == "__main__":
    main()
