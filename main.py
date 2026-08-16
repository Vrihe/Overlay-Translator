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

# torch must be imported at module level — BEFORE QApplication is created.
# Qt DLL initialization (OpenMP, MSVC runtimes) modifies the DLL search path,
# which causes c10.dll to fail if torch is loaded after QApplication.
try:
    import torch
    logging.info(f"PyTorch loaded successfully. Version: {torch.__version__}")
except Exception:
    logging.exception("PyTorch failed to load during entry point initialization")

from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtCore import QObject, QRect, QTimer, pyqtSignal, QThread, Qt
import keyboard

import config
import settings
from overlay.selector import RegionSelector
from capture.screenshot import capture_region
from ocr.engine import recognise

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


def _create_splash() -> QSplashScreen:
    """Create a branded splash screen shown during app initialization."""
    from PyQt5.QtGui import QPixmap, QColor, QPainter, QFont

    pix = QPixmap(440, 160)
    pix.fill(QColor("#1c1c24"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QColor("#a78bfa"))
    title_font = QFont("Segoe UI", 20, QFont.Bold)
    painter.setFont(title_font)
    painter.drawText(pix.rect().adjusted(0, -30, 0, 0), Qt.AlignCenter, "Translator Overlay")

    painter.setPen(QColor("#6b7280"))
    sub_font = QFont("Segoe UI", 10)
    painter.setFont(sub_font)
    painter.drawText(pix.rect().adjusted(0, 40, 0, 0), Qt.AlignCenter, "Loading...")
    painter.end()

    return QSplashScreen(pix, Qt.WindowStaysOnTopHint)


# ── Bridge: keyboard thread → Qt main thread ─────────────

class HotkeyBridge(QObject):
    """Emits *triggered* from any thread; connected slot runs on the main thread."""
    triggered = pyqtSignal()


# ── Worker: Capture → OCR → Translate on background thread ──

class TranslationWorker(QThread):
    finished = pyqtSignal(str, str, str)      # (source_text, translated_text, error_message)
    partial_result = pyqtSignal(str)           # A5: incremental translation chunk for streaming UI
    ocr_done = pyqtSignal(str, QRect)          # D1: OCR finished, emits (recognized_text, anchor)

    def __init__(self, x1: int, y1: int, x2: int, y2: int, text_override: str | None = None, ocr_only: bool = False):
        super().__init__()
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.text_override = text_override
        self.ocr_only = ocr_only

    def run(self):
        logging.debug(f"TranslationWorker started for bbox ({self.x1}, {self.y1}, {self.x2}, {self.y2})")
        anchor = QRect(self.x1, self.y1, self.x2 - self.x1, self.y2 - self.y1)

        # Step 1 & 2: Capture & OCR (unless text_override is provided)
        if self.text_override is not None:
            text = self.text_override
        else:
            try:
                logging.debug("Step 1: Capturing screen region...")
                image = capture_region(self.x1, self.y1, self.x2, self.y2)
            except Exception as e:
                logging.exception("Step 1 Failed: Screen capture error")
                self.finished.emit("", "", f"Ошибка захвата экрана:\n{e}")
                return

            try:
                logging.debug("Step 2: Running OCR recognition...")
                text = recognise(image)
            except Exception as e:
                logging.exception("Step 2 Failed: OCR recognition error")
                self.finished.emit("", "", f"Ошибка OCR:\n{e}")
                return

            if not text:
                logging.info("Step 2 Result: No text recognized in region.")
                self.finished.emit("", "", "Текст не распознан.\nПопробуйте выделить область точнее.")
                return

            # D1: If ocr_only, emit ocr_done and stop here
            if self.ocr_only:
                self.ocr_done.emit(text, anchor)
                return

        # Step 3: LLM Translation
        # Lazy import: openai/anthropic SDKs are loaded here, not at app startup.
        from translate.llm_client import translate, detect_and_translate
        try:
            logging.debug(f"Step 3: Translating text with domain profile '{config.ACTIVE_DOMAIN}'...")
            if getattr(config, "SOURCE_LANG", "auto") == "auto":
                detected_lang, translated = detect_and_translate(text, domain_id=config.ACTIVE_DOMAIN)
            else:
                translated = translate(
                    text,
                    domain_id=config.ACTIVE_DOMAIN,
                    on_chunk=lambda partial: self.partial_result.emit(partial),
                )
        except Exception as e:
            logging.exception("Step 3 Failed: Translation error")
            self.finished.emit(text, "", f"Ошибка перевода:\n{e}\n\nРаспознанный текст:\n{text}")
            return

        self.finished.emit(text, translated, "")


# ── Background OCR engine warm-up ───────────────────────

class OcrWarmupWorker(QThread):
    """Pre-loads the EasyOCR singleton in a background thread.

    Scheduled 3 s after app start so the heavy model load (CRAFT + CRNN, ~2-4 s)
    happens silently while the user reads the UI — not on their first hotkey press.
    torch is already imported at module level so c10.dll is safe to use here.
    """

    def run(self) -> None:
        try:
            logging.info("OcrWarmupWorker: pre-loading EasyOCR engine...")
            from ocr.engine import get_reader
            get_reader()
            logging.info("OcrWarmupWorker: EasyOCR engine ready.")
        except Exception:
            logging.exception("OcrWarmupWorker: pre-load failed (non-fatal, will retry on first use)")


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
            self._tray.act_live_monitor.triggered.connect(self._toggle_live_monitoring)
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

        # Schedule cache warm-up (100 ms) and OCR engine warm-up (3 s) after app start.
        QTimer.singleShot(100, self._warm_up_cache)
        self._ocr_warmup: OcrWarmupWorker | None = None
        QTimer.singleShot(3000, self._warm_up_ocr)

    def _warm_up_cache(self) -> None:
        """Pre-load recent translations into L1 in-memory cache."""
        try:
            from cache.store import warm_cache
            count = warm_cache(limit=50)
            logging.info(f"Cache warmed with {count} recent translations from history.")
        except Exception:
            logging.exception("Failed to warm translation cache")

    def _warm_up_ocr(self) -> None:
        """Launch the OCR warm-up worker (called once via QTimer)."""
        self._ocr_warmup = OcrWarmupWorker()
        self._ocr_warmup.start()

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

            # Check if this selection was triggered for Live Monitor mode (D2)
            if getattr(self, "_live_selection_mode", False):
                self._live_selection_mode = False
                self._start_live_monitoring(x1, y1, x2, y2)
                return

            # D1: Check if OCR Preview/Edit mode is enabled
            if getattr(config, "ENABLE_OCR_PREVIEW", False):
                self._worker = TranslationWorker(x1, y1, x2, y2, ocr_only=True)
                self._worker.ocr_done.connect(
                    lambda text, anc: self._on_ocr_preview_requested(x1, y1, x2, y2, text, anc)
                )
                self._worker.start()
                return

            # Normal path: direct translation
            self._start_translation_pipeline(x1, y1, x2, y2, anchor=anchor)
        except Exception:
            logging.exception("Error handling region selection in main app thread")

    def _start_translation_pipeline(self, x1: int, y1: int, x2: int, y2: int, anchor: QRect, text_override: str | None = None) -> None:
        """Start background translation worker for (x1, y1, x2, y2) or with text_override."""
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
        self._worker = TranslationWorker(x1, y1, x2, y2, text_override=text_override)
        self._worker.finished.connect(
            lambda src, tr, err: self._on_translation_finished(src, tr, err, anchor)
        )
        self._worker.partial_result.connect(
            lambda partial: self._on_partial_translation(partial),
            Qt.QueuedConnection,
        )
        self._worker.start()

    def _on_ocr_preview_requested(self, x1: int, y1: int, x2: int, y2: int, raw_text: str, anchor: QRect) -> None:
        """D1: Display OCR preview popup allowing user to edit text before translating."""
        from ui.ocr_preview_popup import OcrPreviewPopup
        self._close_popup()
        preview = OcrPreviewPopup(raw_text, anchor)
        preview.confirmed.connect(
            lambda edited: self._start_translation_pipeline(x1, y1, x2, y2, anchor, text_override=edited)
        )
        preview.show()

    # ── D2: Live Monitor Mode ────────────────────────────

    def _toggle_live_monitoring(self, checked: bool) -> None:
        """D2: Toggle live monitoring on or off."""
        if checked:
            self._live_selection_mode = True
            self._show_selector()
        else:
            self._stop_live_monitoring()

    def _start_live_monitoring(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """D2: Start live background monitor for specified screen region."""
        from capture.live_monitor import LiveMonitor
        if hasattr(self, "_live_monitor") and self._live_monitor is not None:
            self._live_monitor.stop()

        self._live_monitor = LiveMonitor(x1, y1, x2, y2, interval_sec=2.0)
        self._live_monitor.region_changed.connect(
            lambda lx1, ly1, lx2, ly2: self._on_region_selected(lx1, ly1, lx2, ly2)
        )
        self._live_monitor.start()

        if self._tray is not None:
            self._tray.showMessage(
                "Живой мониторинг запущен",
                "Область автоматически проверяется каждые 2 сек.",
                TrayIcon.Information,
                3000,
            )

    def _stop_live_monitoring(self) -> None:
        """D2: Stop live monitor if active."""
        if hasattr(self, "_live_monitor") and self._live_monitor is not None:
            self._live_monitor.stop()
            self._live_monitor = None
            if self._tray is not None:
                self._tray.showMessage(
                    "Живой мониторинг остановлен",
                    "Автоматическое отслеживание области отключено.",
                    TrayIcon.Information,
                    2000,
                )

    def _on_partial_translation(self, partial_text: str) -> None:
        """A5: Update the loading popup with partial streaming translation text.

        Called from the main thread (QueuedConnection) while the LLM is still
        generating tokens.  We show the partial text in the popup so the user
        sees the translation appear word-by-word instead of waiting for the
        full response.
        """
        try:
            popup = self._popup
            if popup is None:
                return
            # Only update while still in loading state — once update_content()
            # finalises the popup (is_loading=False) we stop overwriting it.
            if not getattr(popup, "_is_loading", False):
                return
            if not partial_text.strip():
                return
            # Reuse the loading label to show the live translation preview.
            lbl = getattr(popup, "_loading_label", None)
            if lbl is not None:
                try:
                    lbl.setText(partial_text)
                except RuntimeError:
                    pass  # popup was deleted between the signal emit and the slot
        except Exception:
            logging.debug("Ignored error in _on_partial_translation", exc_info=True)

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

        # Show splash immediately — torch is already loaded (module level above),
        # splash covers the remaining init time: MainWindow, TrayIcon, hotkeys.
        splash = _create_splash()
        splash.show()
        app.processEvents()

        # ── First-run: ask for API key if none is configured ─
        if not _has_any_api_key():
            logging.info("No API keys found. Prompting first-run dialog.")
            splash.close()  # hide splash before interactive dialog
            from ui.first_run_dialog import FirstRunDialog
            dlg = FirstRunDialog()
            if dlg.exec_() != FirstRunDialog.Accepted:
                logging.info("First-run dialog cancelled. Exiting.")
                sys.exit(0)

        translator = TranslatorApp(app)
        splash.finish(translator._main_window)  # fade out once main window is ready
        sys.exit(translator.run())
    except Exception:
        logging.exception("Unhandled exception in main()")
        sys.exit(1)


if __name__ == "__main__":
    main()
