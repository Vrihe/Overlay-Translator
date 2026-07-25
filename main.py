"""
Translator Overlay — entry point.

Full pipeline:
  Ctrl+Shift+R  →  region selector  →  screenshot (mss)
                →  OCR (EasyOCR)     →  translate (LLM)
                →  result popup

Main window is shown on startup with sidebar navigation.
System-tray icon runs in parallel for quick access.
"""

import os
import sys
import logging
import threading

# ── Early Logging Configuration ──────────────────────────

def _init_logging() -> str:
    """Initialize logging to %APPDATA%/translator-overlay/app.log at DEBUG level before anything else."""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(appdata, "translator-overlay")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    logging.basicConfig(
        filename=log_file,
        filemode="a",
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        encoding="utf-8",
    )
    logging.info("================ Application Initialization Started ================")
    logging.info(f"Log file: {log_file}")
    logging.info(f"Python executable: {sys.executable}")
    logging.info(f"Frozen executable: {getattr(sys, 'frozen', False)}")
    return log_file

_log_file_path = _init_logging()

# ── Global Exception Hooks ────────────────────────────────

def _global_excepthook(exctype, value, tb):
    """Global hook to catch and log any unhandled exceptions in the main thread."""
    logging.critical("Uncaught exception in main thread:", exc_info=(exctype, value, tb))
    sys.__excepthook__(exctype, value, tb)

def _thread_excepthook(args):
    """Global hook to catch and log any unhandled exceptions in worker threads."""
    logging.critical(
        f"Uncaught exception in thread '{args.thread.name}':",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )

sys.excepthook = _global_excepthook
if hasattr(threading, "excepthook"):
    threading.excepthook = _thread_excepthook

import ctypes
import time
import traceback

# Fix Windows DLL path resolution for PyTorch & C++ runtimes in PyInstaller frozen app
def _preload_torch_dlls():
    import ctypes
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    os.environ["OMP_NUM_THREADS"] = "1"

    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        torch_lib = os.path.join(base_dir, "torch", "lib")
        logging.debug(f"_MEIPASS base_dir: {base_dir}, torch_lib: {torch_lib}")
        if os.path.exists(torch_lib):
            try:
                ctypes.windll.kernel32.SetDllDirectoryW(torch_lib)
                logging.debug("SetDllDirectoryW(torch_lib) succeeded.")
            except Exception as e:
                logging.warning(f"SetDllDirectoryW failed: {e}")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(torch_lib)
                    logging.debug("add_dll_directory(torch_lib) succeeded.")
                except Exception as e:
                    logging.warning(f"add_dll_directory(torch_lib) failed: {e}")
            os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(base_dir)
                logging.debug("add_dll_directory(base_dir) succeeded.")
            except Exception as e:
                logging.warning(f"add_dll_directory(base_dir) failed: {e}")

        for dll_name in [
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "msvcp140.dll",
            "vcomp140.dll",
            "libiomp5md.dll",
            "asmjit.dll",
            "fbgemm.dll",
            "uv.dll",
            "torch_cpu.dll",
            "c10.dll",
            "torch.dll",
        ]:
            dll_path = os.path.join(torch_lib, dll_name)
            if os.path.exists(dll_path):
                try:
                    ctypes.CDLL(dll_path)
                    logging.debug(f"Preloaded DLL: {dll_name}")
                except Exception as e:
                    logging.warning(f"Failed preloading DLL {dll_name}: {e}")

_preload_torch_dlls()

try:
    import torch
    logging.info(f"PyTorch loaded successfully. Version: {torch.__version__}")
except Exception:
    logging.exception("PyTorch failed to load during entry point initialization")

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
        logging.debug(f"TranslationWorker started for bbox ({self.x1}, {self.y1}, {self.x2}, {self.y2})")

        # Step 1: Capture Screenshot
        try:
            logging.debug("Step 1: Capturing screen region...")
            image = capture_region(self.x1, self.y1, self.x2, self.y2)
            logging.debug(f"Step 1 Complete: Image size {image.size if image else 'None'}")
        except Exception as e:
            logging.exception("Step 1 Failed: Screen capture error")
            self.finished.emit("", "", f"Ошибка захвата экрана:\n{e}")
            return

        # Step 2: OCR Recognition
        try:
            logging.debug("Step 2: Running OCR recognition...")
            text = recognise(image)
            logging.debug(f"Step 2 Complete: OCR recognized text length = {len(text) if text else 0}")
        except Exception as e:
            logging.exception("Step 2 Failed: OCR recognition error")
            self.finished.emit("", "", f"Ошибка OCR:\n{e}")
            return

        if not text:
            logging.info("Step 2 Result: No text recognized in region.")
            self.finished.emit("", "", "Текст не распознан.\nПопробуйте выделить область точнее.")
            return

        # Step 3: LLM Translation
        try:
            logging.debug(f"Step 3: Translating text with domain profile '{config.ACTIVE_DOMAIN}'...")
            translated = translate(text, domain_id=config.ACTIVE_DOMAIN)
            logging.debug("Step 3 Complete: Translation succeeded.")
        except Exception as e:
            logging.exception("Step 3 Failed: Translation error")
            self.finished.emit(text, "", f"Ошибка перевода:\n{e}\n\nРаспознанный текст:\n{text}")
            return

        self.finished.emit(text, translated, "")


# ── Application ──────────────────────────────────────────

class TranslatorApp:
    """Owns the QApplication, main window, tray icon, hotkey, selector, and result popups."""

    def __init__(self, app: QApplication):
        logging.info("Initializing TranslatorApp...")
        self.app = app
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("Translator Overlay")

        # ── Main window ─────────────────────────────────
        try:
            self._main_window = MainWindow()
        except Exception:
            logging.exception("Failed to initialize MainWindow")
            raise

        # ── System tray ──────────────────────────────────
        try:
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
        except Exception:
            logging.exception("Failed to initialize TrayIcon")
            raise

        # ── Show main window on startup ──────────────────
        self._main_window.set_tray_icon(self._tray)
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
        try:
            keyboard.add_hotkey(config.HOTKEY, self._bridge.triggered.emit)
            keyboard.add_hotkey(config.SETTINGS_HOTKEY, self._settings_bridge.triggered.emit)
            logging.info(f"Registered hotkeys: translate='{config.HOTKEY}', settings='{config.SETTINGS_HOTKEY}'")
        except Exception:
            logging.exception("Failed to register global hotkeys")

    # ── Main window toggle ───────────────────────────────

    def _toggle_main_window(self) -> None:
        """Toggle main window visibility (for tray icon click)."""
        try:
            self._main_window.toggle_visibility()
        except Exception:
            logging.exception("Error toggling main window visibility")

    # ── Selector lifecycle ───────────────────────────────

    def _show_selector(self) -> None:
        """Create and show the region-selection overlay."""
        try:
            logging.debug("Showing region selector overlay...")
            if self._selector is not None:
                logging.debug("Region selector already visible.")
                return
            self._close_popup()

            self._selector = RegionSelector()
            self._selector.region_selected.connect(self._on_region_selected)
            self._selector.selection_cancelled.connect(self._on_cancelled)
            self._selector.destroyed.connect(self._on_selector_destroyed)
            self._selector.activate()
        except Exception:
            logging.exception("Error showing region selector")

    def _on_cancelled(self) -> None:
        logging.debug("Region selection cancelled by user.")

    def _on_selector_destroyed(self) -> None:
        self._selector = None

    # ── Pipeline: capture → OCR → translate → popup ──────

    def _on_region_selected(self, x1: int, y1: int, x2: int, y2: int) -> None:
        try:
            logging.info(f"Region selected: ({x1}, {y1}) to ({x2}, {y2})")
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
                logging.debug("Terminating existing background translation worker...")
                self._worker.terminate()
                self._worker.wait()

            # Start translation pipeline in background thread
            self._worker = TranslationWorker(x1, y1, x2, y2)
            self._worker.finished.connect(
                lambda src, tr, err: self._on_translation_finished(src, tr, err, anchor)
            )
            self._worker.start()
        except Exception:
            logging.exception("Error handling region selection in main app thread")

    def _on_translation_finished(self, source: str, translated: str, error_msg: str, anchor: QRect) -> None:
        try:
            self._worker = None
            if error_msg:
                logging.warning(f"Translation finished with error: {error_msg}")
                self._show_error(error_msg, anchor)
            else:
                logging.info(f"Translation finished successfully. Source length: {len(source)}, Translated length: {len(translated)}")
                self._show_result(source, translated, anchor)
        except Exception:
            logging.exception("Error presenting translation result/error popup")

    # ── Popup helpers ────────────────────────────────────

    def _show_result(self, source: str, translated: str, anchor: QRect) -> None:
        try:
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
        except Exception:
            logging.exception("Error showing result popup")

    def _show_error(self, message: str, anchor: QRect) -> None:
        try:
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
        except Exception:
            logging.exception("Error showing error popup")

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.hide()
                self._popup.deleteLater()
            except RuntimeError:
                pass
            except Exception:
                logging.exception("Error closing popup")
            self._popup = None

    def _on_popup_destroyed(self) -> None:
        self._popup = None

    # ── Quit ─────────────────────────────────────────────

    def _quit(self) -> None:
        """Full shutdown: unhook keyboard, close main window, hide tray, exit Qt loop."""
        try:
            logging.info("Shutting down application...")
            keyboard.unhook_all()
            self._close_popup()
            self._main_window.closeEvent = lambda e: e.accept()
            self._main_window.close()
            self._tray.hide()
            self.app.quit()
        except Exception:
            logging.exception("Error during app shutdown")

    # ── Run ──────────────────────────────────────────────

    def run(self) -> int:
        try:
            logging.info("Starting Qt event loop.")
            return self.app.exec_()
        except KeyboardInterrupt:
            self._quit()
            return 0
        except Exception:
            logging.exception("Error in main Qt event loop")
            return 1


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
    try:
        _hide_console()

        app = QApplication(sys.argv)

        # ── First-run: ask for API key if none is configured ─
        if not _has_any_api_key():
            logging.info("No API keys found. Prompting first-run dialog.")
            from ui.first_run_dialog import FirstRunDialog
            dlg = FirstRunDialog()
            if dlg.exec_() != FirstRunDialog.Accepted:
                logging.info("First-run dialog cancelled. Exiting.")
                sys.exit(0)

        translator = TranslatorApp(app)
        sys.exit(translator.run())
    except Exception:
        logging.exception("Unhandled exception in main()")
        sys.exit(1)


if __name__ == "__main__":
    main()
