"""
Translator Overlay — entry point.

Runs the PyQt5 event loop on the main thread and registers a global
hotkey (Ctrl+Shift+T) via the *keyboard* library.  The hotkey callback
fires from a background thread, so we bridge it into Qt with a
cross-thread signal (``HotkeyBridge``).

Press Ctrl+Shift+T  → fullscreen region-selector overlay appears.
Drag a rectangle     → coordinates printed to console.
Escape               → overlay dismissed, no action.
Ctrl+C in terminal   → quit.
"""

import sys
import time

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal
import keyboard

import config
from overlay.selector import RegionSelector
from capture.screenshot import capture_region
from ocr.engine import recognise
from translate.llm_client import translate


# ── Bridge: keyboard thread → Qt main thread ─────────────

class HotkeyBridge(QObject):
    """Emits *triggered* from any thread; connected slot runs on the main thread."""
    triggered = pyqtSignal()


# ── Application ──────────────────────────────────────────

class TranslatorApp:
    """Thin wrapper that owns the QApplication, hotkey, and selector."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self._bridge = HotkeyBridge()
        self._bridge.triggered.connect(self._show_selector)

        self._selector: RegionSelector | None = None

        # Register the global hotkey (fires on a background thread).
        keyboard.add_hotkey(config.HOTKEY, self._bridge.triggered.emit)

    # ── Selector lifecycle ───────────────────────────────

    def _show_selector(self) -> None:
        """Create and show the region-selection overlay."""
        # If one is already open, ignore.
        if self._selector is not None:
            return

        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_cancelled)
        self._selector.destroyed.connect(self._on_selector_destroyed)
        self._selector.activate()

    def _on_region_selected(self, x1: int, y1: int, x2: int, y2: int) -> None:
        w = x2 - x1
        h = y2 - y1
        print(f"Selected region: ({x1}, {y1}) → ({x2}, {y2})  [{w}×{h} px]")

        # ── Capture → OCR → Translate pipeline ─────────────
        t0 = time.perf_counter()

        print("  Capturing…")
        image = capture_region(x1, y1, x2, y2)

        print("  Running OCR…")
        text = recognise(image)

        if not text:
            print(f"  (no text recognised)  [{time.perf_counter() - t0:.2f}s]\n")
            return

        print(f"  OCR result: {text[:80]}{'...' if len(text) > 80 else ''}")

        print("  Translating…")
        try:
            translated = translate(text)
        except Exception as e:
            print(f"  Translation error: {e}\n")
            return

        elapsed = time.perf_counter() - t0
        print(f"  Done in {elapsed:.2f}s\n")

        print("─" * 40)
        print(f"  SRC: {text}")
        print(f"  →  : {translated}")
        print("─" * 40 + "\n")

    def _on_cancelled(self) -> None:
        print("Selection cancelled (Escape)")

    def _on_selector_destroyed(self) -> None:
        self._selector = None

    # ── Run ──────────────────────────────────────────────

    def run(self) -> int:
        print(f"Translator Overlay started.")
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
