"""
Translator Overlay — entry point.

Full pipeline:
  Ctrl+Shift+T  →  region selector  →  screenshot (mss)
               →  OCR (pytesseract) →  translate (LLM)
               →  result popup

Runs as a background application with a system-tray icon.
No console window is shown (use pythonw.exe or the .pyw extension).
"""

import ctypes
import sys
import time
import traceback

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, QRect, pyqtSignal
import keyboard

import config
from overlay.selector import RegionSelector
from capture.screenshot import capture_region
from ocr.engine import recognise
from translate.llm_client import translate
from ui.result_popup import ResultPopup
from tray.tray_icon import TrayIcon


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


# ── Application ──────────────────────────────────────────

class TranslatorApp:
    """Owns the QApplication, tray icon, hotkey, selector, and result popups."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("Translator Overlay")

        # ── System tray ──────────────────────────────────
        self._tray = TrayIcon()
        self._tray.act_translate.triggered.connect(self._show_selector)
        self._tray.act_exit.triggered.connect(self._quit)
        self._tray.show()

        # ── Hotkey bridge ────────────────────────────────
        self._bridge = HotkeyBridge()
        self._bridge.triggered.connect(self._show_selector)

        self._selector: RegionSelector | None = None
        self._popup: ResultPopup | None = None

        # Register the global hotkey (fires on a background thread).
        keyboard.add_hotkey(config.HOTKEY, self._bridge.triggered.emit)

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
        t0 = time.perf_counter()

        # ── Step 1: Capture ──────────────────────────────
        try:
            image = capture_region(x1, y1, x2, y2)
        except Exception as e:
            self._show_error(f"Ошибка захвата экрана:\n{e}", anchor)
            traceback.print_exc()
            return

        # ── Step 2: OCR ──────────────────────────────────
        try:
            text = recognise(image)
        except Exception as e:
            self._show_error(f"Ошибка OCR:\n{e}", anchor)
            traceback.print_exc()
            return

        if not text:
            self._show_error("Текст не распознан.\nПопробуйте выделить область точнее.", anchor)
            return

        # ── Step 3: Translate ────────────────────────────
        try:
            translated = translate(text)
        except Exception as e:
            traceback.print_exc()
            self._show_error(
                f"Ошибка перевода:\n{e}\n\nРаспознанный текст:\n{text}",
                anchor,
            )
            return

        # ── Step 4: Show result popup ────────────────────
        self._show_result(text, translated, anchor)

    # ── Popup helpers ────────────────────────────────────

    def _show_result(self, source: str, translated: str, anchor: QRect) -> None:
        self._close_popup()
        self._popup = ResultPopup(source, translated, anchor)
        self._popup.destroyed.connect(self._on_popup_destroyed)
        self._popup.show()

    def _show_error(self, message: str, anchor: QRect) -> None:
        self._close_popup()
        self._popup = ResultPopup("", message, anchor, is_error=True)
        self._popup.destroyed.connect(self._on_popup_destroyed)
        self._popup.show()

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.close()
            except RuntimeError:
                pass
            self._popup = None

    def _on_popup_destroyed(self) -> None:
        self._popup = None

    # ── Quit ─────────────────────────────────────────────

    def _quit(self) -> None:
        """Full shutdown: unhook keyboard, hide tray, exit Qt loop."""
        keyboard.unhook_all()
        self._close_popup()
        self._tray.hide()
        self.app.quit()

    # ── Run ──────────────────────────────────────────────

    def run(self) -> int:
        try:
            return self.app.exec_()
        except KeyboardInterrupt:
            self._quit()
            return 0


def main() -> None:
    _hide_console()
    translator = TranslatorApp()
    sys.exit(translator.run())


if __name__ == "__main__":
    main()
