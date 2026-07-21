"""
Translator Overlay — entry point.

Full pipeline:
  Ctrl+Shift+T  →  region selector  →  screenshot (mss)
               →  OCR (pytesseract) →  translate (LLM)
               →  result popup

Runs the PyQt5 event loop on the main thread and registers a global
hotkey via the *keyboard* library.  The hotkey callback fires from a
background thread and is bridged into Qt with ``HotkeyBridge``.
"""

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


# ── Bridge: keyboard thread → Qt main thread ─────────────

class HotkeyBridge(QObject):
    """Emits *triggered* from any thread; connected slot runs on the main thread."""
    triggered = pyqtSignal()


# ── Application ──────────────────────────────────────────

class TranslatorApp:
    """Owns the QApplication, hotkey, selector, and result popups."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

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
        # Close any existing popup before a new selection.
        self._close_popup()

        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_cancelled)
        self._selector.destroyed.connect(self._on_selector_destroyed)
        self._selector.activate()

    def _on_cancelled(self) -> None:
        print("Selection cancelled (Escape)")

    def _on_selector_destroyed(self) -> None:
        self._selector = None

    # ── Pipeline: capture → OCR → translate → popup ──────

    def _on_region_selected(self, x1: int, y1: int, x2: int, y2: int) -> None:
        anchor = QRect(x1, y1, x2 - x1, y2 - y1)
        w, h = anchor.width(), anchor.height()
        print(f"Selected region: ({x1}, {y1}) → ({x2}, {y2})  [{w}×{h} px]")

        t0 = time.perf_counter()

        # ── Step 1: Capture ──────────────────────────────
        try:
            print("  Capturing…")
            image = capture_region(x1, y1, x2, y2)
        except Exception as e:
            self._show_error(f"Ошибка захвата экрана:\n{e}", anchor)
            traceback.print_exc()
            return

        # ── Step 2: OCR ──────────────────────────────────
        try:
            print("  Running OCR…")
            text = recognise(image)
        except Exception as e:
            self._show_error(f"Ошибка OCR:\n{e}", anchor)
            traceback.print_exc()
            return

        if not text:
            elapsed = time.perf_counter() - t0
            print(f"  (no text recognised)  [{elapsed:.2f}s]")
            self._show_error("Текст не распознан.\nПопробуйте выделить область точнее.", anchor)
            return

        print(f"  OCR result: {text[:80]}{'…' if len(text) > 80 else ''}")

        # ── Step 3: Translate ────────────────────────────
        try:
            print("  Translating…")
            translated = translate(text)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  Translation error: {e}  [{elapsed:.2f}s]")
            traceback.print_exc()
            # Show the OCR text even if translation failed.
            self._show_error(
                f"Ошибка перевода:\n{e}\n\nРаспознанный текст:\n{text}",
                anchor,
            )
            return

        elapsed = time.perf_counter() - t0
        print(f"  Done in {elapsed:.2f}s")
        print(f"  SRC: {text[:80]}")
        print(f"  →  : {translated[:80]}\n")

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
                pass  # already deleted
            self._popup = None

    def _on_popup_destroyed(self) -> None:
        self._popup = None

    # ── Run ──────────────────────────────────────────────

    def run(self) -> int:
        print("Translator Overlay started.")
        print(f"Press  {config.HOTKEY.upper()}  to select a screen region.")
        print("Press  Ctrl+C  in the terminal to exit.\n")
        try:
            return self.app.exec_()
        except KeyboardInterrupt:
            print("\nShutting down…")
            return 0
        finally:
            keyboard.unhook_all()


def main() -> None:
    translator = TranslatorApp()
    sys.exit(translator.run())


if __name__ == "__main__":
    main()
