"""
Translator Overlay — entry point.

Full pipeline:
  Ctrl+Shift+R  →  region selector  →  screenshot (mss)
                →  OCR (RapidOCR)    →  translate (LLM)
                →  result popup

Main window is shown on startup with sidebar navigation.
System-tray icon runs in parallel for quick access.
"""

import logging
import os
import sys
import threading

# ── Early Logging Configuration ──────────────────────────


def _init_logging() -> str:
    """Initialize logging to %APPDATA%/translator-overlay/app.log at DEBUG level before anything else."""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(appdata, "translator-overlay")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        handlers=[handler],
    )
    # At DEBUG the HTTP SDKs dump whole request bodies (the captured screen text)
    # into the log; only their warnings are useful here.
    for noisy in ("openai", "anthropic", "httpx", "httpcore", "urllib3", "huggingface_hub", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
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

# Native crashes (segfault, abort() from qFatal or a C++ extension) bypass both
# hooks above and kill the process without a trace; faulthandler still dumps
# the Python stack of every thread. The file stays open for the process lifetime.
import faulthandler

_crash_log = open(os.path.join(os.path.dirname(_log_file_path), "crash.log"), "a", encoding="utf-8")
faulthandler.enable(file=_crash_log, all_threads=True)

# ── Restart hand-over ────────────────────────────────────
# A restart (settings → "Сохранить" for restart-only options) launches the new
# copy with --wait-pid <old pid>; it waits here for the old process to exit, so
# the single-instance check below does not just re-activate the closing window.
_WAIT_PID_FLAG = "--wait-pid"


def _wait_for_previous_instance(timeout_ms: int = 15000) -> None:
    if _WAIT_PID_FLAG not in sys.argv:
        return
    i = sys.argv.index(_WAIT_PID_FLAG)
    try:
        pid = int(sys.argv[i + 1])
    except (IndexError, ValueError):
        pid = 0
    del sys.argv[i : i + 2]
    if not pid or sys.platform != "win32":
        return
    import ctypes as _ctypes

    k32 = _ctypes.windll.kernel32
    handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        k32.WaitForSingleObject(handle, timeout_ms)
        k32.CloseHandle(handle)
    logging.info(f"Restarted after process {pid} exited.")


# ── Single instance ──────────────────────────────────────
# Checked before Qt loads so a duplicate launch exits immediately: a second
# copy would add a second tray icon and register every global hotkey twice.
_instance_guard = None
if __name__ == "__main__":
    _wait_for_previous_instance()
    from single_instance import SingleInstance

    _instance_guard = SingleInstance()
    if not _instance_guard.acquire():
        _notified = _instance_guard.notify_existing()
        logging.info(f"Another instance is already running (window activated: {_notified}). Exiting.")
        sys.exit(0)

import ctypes

# onnxruntime must be imported BEFORE PyQt5. PyQt5 ships an old MSVC runtime
# (msvcp140.dll 14.26) next to Qt5Core.dll; once Qt loads it, onnxruntime (needs
# >= 14.40) fails with "DLL initialization routine failed". Loaded first, it pulls
# in the newer runtime and Qt reuses it. Costs ~0.5 s at startup.
# The frozen build does this even earlier in pyi_rth_onnxruntime.py, because
# PyInstaller's PyQt5 runtime hook loads QtCore before main.py runs.
try:
    import onnxruntime  # noqa: F401
except Exception:
    logging.exception("onnxruntime failed to load; OCR will be unavailable")

import keyboard
from PyQt5.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, QtMsgType, pyqtSignal, qInstallMessageHandler
from PyQt5.QtWidgets import QApplication, QSplashScreen


def _qt_message_handler(mode, context, message):
    """Route Qt's own diagnostics (normally stderr only) into app.log.

    A qFatal (e.g. "QThread: Destroyed while thread is still running") still
    aborts the process after this returns, but the reason is now on disk.
    """
    level = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }.get(mode, logging.WARNING)
    logging.log(level, "Qt: %s", message)


qInstallMessageHandler(_qt_message_handler)

import config
from capture.screenshot import capture_region
from i18n import tr
from ocr.engine import recognise
from overlay.selector import RegionSelector
from tray.tray_icon import TrayIcon
from ui.main_window import MainWindow
from ui.result_popup import ResultPopup

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
    from PyQt5.QtGui import QPainter, QPen, QPixmap

    from ui import theme

    pix = QPixmap(440, 160)
    pix.fill(theme.qcolor("bg"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(theme.qcolor("line"), 1))
    painter.drawRect(pix.rect().adjusted(0, 0, -1, -1))
    painter.fillRect(0, 0, pix.width(), 2, theme.qcolor("accent"))

    painter.setPen(theme.qcolor("text"))
    painter.setFont(theme.display_font(20, spacing=108))
    painter.drawText(pix.rect().adjusted(0, -30, 0, 0), Qt.AlignCenter, "TRANSLATOR OVERLAY")

    painter.setPen(theme.qcolor("muted"))
    painter.setFont(theme.body_font(9, medium=True, spacing=120))
    painter.drawText(pix.rect().adjusted(0, 40, 0, 0), Qt.AlignCenter, "LOADING...")
    painter.end()

    return QSplashScreen(pix, Qt.WindowStaysOnTopHint)


# ── Bridge: keyboard thread → Qt main thread ─────────────


def _anchor_key(anchor: QRect | None) -> tuple[int, int, int, int] | None:
    """A region's identity for remembering where its popup was dragged to."""
    if anchor is None:
        return None
    return anchor.x(), anchor.y(), anchor.width(), anchor.height()


class HotkeyBridge(QObject):
    """Emits *triggered* from any thread; connected slot runs on the main thread."""

    triggered = pyqtSignal()


# ── Worker: Capture → OCR → Translate on background thread ──


class TranslationWorker(QThread):
    translation_done = pyqtSignal(str, str, str)  # (source_text, translated_text, error_message)
    partial_result = pyqtSignal(str)  # A5: incremental translation chunk for streaming UI
    ocr_done = pyqtSignal(str, QRect)  # D1: OCR finished, emits (recognized_text, anchor)

    def __init__(self, x1: int, y1: int, x2: int, y2: int, text_override: str | None = None, ocr_only: bool = False):
        super().__init__()
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.text_override = text_override
        self.ocr_only = ocr_only
        # Set when the local NLLB backend was unavailable and the API was used
        # instead; read by TranslatorApp after translation_done.
        self.backend_notice: str = ""

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
                self.translation_done.emit("", "", tr("Ошибка захвата экрана:\n{error}", error=e))
                return

            try:
                logging.debug("Step 2: Running OCR recognition...")
                text = recognise(image)
            except Exception as e:
                logging.exception("Step 2 Failed: OCR recognition error")
                self.translation_done.emit("", "", tr("Ошибка OCR:\n{error}", error=e))
                return

            if not text:
                logging.info("Step 2 Result: No text recognized in region.")
                self.translation_done.emit("", "", tr("Текст не распознан.\nПопробуйте выделить область точнее."))
                return

            # D1: If ocr_only, emit ocr_done and stop here
            if self.ocr_only:
                self.ocr_done.emit(text, anchor)
                return

        # Step 3: Translation via the active backend (API or local NLLB).
        # Lazy import: openai/anthropic SDKs and ctranslate2 load here, not at startup.
        from translate.backend import detect_and_translate, take_notice, translate

        stream_cb = (
            (lambda partial: self.partial_result.emit(partial)) if getattr(config, "ENABLE_STREAMING", True) else None
        )
        try:
            logging.debug(
                f"Step 3: Translating text with domain profile '{config.ACTIVE_DOMAIN}' (streaming={stream_cb is not None})..."
            )
            if getattr(config, "SOURCE_LANG", "auto") == "auto":
                detected_lang, translated = detect_and_translate(
                    text,
                    domain_id=config.ACTIVE_DOMAIN,
                    on_chunk=stream_cb,
                )
            else:
                translated = translate(
                    text,
                    domain_id=config.ACTIVE_DOMAIN,
                    on_chunk=stream_cb,
                )
        except Exception as e:
            logging.exception("Step 3 Failed: Translation error")
            self.translation_done.emit(
                text, "", tr("Ошибка перевода:\n{error}\n\nРаспознанный текст:\n{text}", error=e, text=text)
            )
            return

        self.backend_notice = take_notice()
        self.translation_done.emit(text, translated, "")


# ── Background OCR engine warm-up ───────────────────────


class OcrWarmupWorker(QThread):
    """Pre-loads the RapidOCR engine and the langid model in a background thread.

    Scheduled 3 s after app start so the ONNX model load plus the first DirectML
    run (~2-4 s) and, for backends that use it, the langid model load (~1.5 s) happen silently while the user
    reads the UI — not on their first hotkey press.
    """

    def run(self) -> None:
        try:
            logging.info("OcrWarmupWorker: pre-loading OCR engine...")
            from ocr.engine import warm_up

            warm_up()
            logging.info("OcrWarmupWorker: OCR engine ready.")
        except Exception:
            logging.exception("OcrWarmupWorker: pre-load failed (non-fatal, will retry on first use)")
        try:
            # Unpickling the langid model holds the GIL for ~1 s and freezes the UI;
            # skip it unless the backend needs it (it still loads on first use).
            from translate.backend import uses_langid

            if not uses_langid():
                return
            from translate.lang_detect import get_detector

            get_detector("langid").detect("warm up")
            logging.info("OcrWarmupWorker: langid model ready.")
        except Exception:
            logging.exception("OcrWarmupWorker: langid pre-load failed (non-fatal)")


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
            self._tray.act_history.triggered.connect(lambda: self._main_window.show_and_switch(MainWindow.PAGE_HISTORY))
            self._tray.act_exit.triggered.connect(self._quit)
            self._tray.act_presets.triggered.connect(self._show_presets_dialog)
            self._tray.preset_quick_start.connect(self._on_preset_translate)
            self._tray.show()
        except Exception:
            logging.exception("Failed to initialize TrayIcon")
            raise

        # ── Show main window on startup ──────────────────
        self._main_window.set_tray_icon(self._tray)
        self._main_window.restart_requested.connect(self._restart)
        self._main_window.update_install_started.connect(self._quit)
        self._main_window.add_region_requested.connect(self._add_region)
        self._main_window.manage_regions_requested.connect(self._show_presets_dialog)
        self._main_window.monitor_region_requested.connect(self._on_preset_monitor)
        self._main_window.stop_monitoring_requested.connect(self._stop_live_monitoring)
        self._main_window.show()

        # ── Hotkey bridges ───────────────────────────────
        self._bridge = HotkeyBridge()
        self._bridge.triggered.connect(self._show_selector)

        self._settings_bridge = HotkeyBridge()
        self._settings_bridge.triggered.connect(lambda: self._main_window.show_and_switch(MainWindow.PAGE_SETTINGS))

        # A repeated launch of the app signals this instance to show its window.
        self._activate_bridge = HotkeyBridge()
        self._activate_bridge.triggered.connect(self._main_window.show_window)
        if _instance_guard is not None:
            _instance_guard.listen(self._activate_bridge.triggered.emit)

        self._selector: RegionSelector | None = None
        self._popup: ResultPopup | None = None
        self._worker: TranslationWorker | None = None
        self._request_seq = 0  # id of the newest translation request
        self._last_manual_seq = 0  # id of the newest request the user made (not live)
        self._pending_request = None  # the newest request waiting for a running worker
        self._retired_workers: set = set()  # replaced workers kept alive until they finish
        # Where the user dragged a popup to, per region (anchor rect): the next popup for
        # that region (live monitoring, a preset bind) opens there, not at the default spot.
        self._user_popup_pos: dict[tuple[int, int, int, int], QPoint] = {}
        self._presets_dialog = None  # RegionPresetsDialog instance (if open)
        self._preset_hotkeys: list[str] = []
        self._preset_bridges: list[HotkeyBridge] = []

        # Register global hotkeys (fire on a background thread). Settings → Hotkeys
        # changes them at run time; a focused hotkey field pauses them all.
        self._app_hotkey_handles: list = []
        self._hotkeys_paused = False
        self._register_app_hotkeys()
        self._main_window.hotkeys_changed.connect(self._register_app_hotkeys)
        self._main_window.hotkey_capture.connect(self._pause_hotkeys)

        # Register individual preset hotkeys
        self._register_preset_hotkeys()

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

            # Check if this selection was triggered for Preset creation
            if getattr(self, "_preset_creation_mode", False):
                self._preset_creation_mode = False
                self._on_preset_region_selected(x1, y1, x2, y2)
                return

            # D1: Check if OCR Preview/Edit mode is enabled
            if getattr(config, "ENABLE_OCR_PREVIEW", False):
                self._replace_worker(TranslationWorker(x1, y1, x2, y2, ocr_only=True))
                self._worker.ocr_done.connect(
                    lambda text, anc: self._on_ocr_preview_requested(x1, y1, x2, y2, text, anc)
                )
                self._worker.start()
                return

            # Normal path: direct translation
            self._start_translation_pipeline(x1, y1, x2, y2, anchor=anchor)
        except Exception:
            logging.exception("Error handling region selection in main app thread")

    def _start_translation_pipeline(
        self, x1: int, y1: int, x2: int, y2: int, anchor: QRect, text_override: str | None = None, *, live: bool = False
    ) -> None:
        """Translate (x1, y1, x2, y2), or text_override, on a background worker.

        A running translation is never killed: QThread.terminate() mid-OCR can leave the
        OCR engine broken for the rest of the session. The newest request waits instead
        and runs when the current one ends; an older waiting one is dropped, and a
        finished translation is not shown once the user has asked for a newer one.
        A live-monitoring update (``live``) keeps the open popup and refreshes it in
        place instead of replacing it with a new "Переводим…" one.
        """
        self._request_seq += 1
        if not live:
            self._last_manual_seq = self._request_seq
        request = (self._request_seq, x1, y1, x2, y2, anchor, text_override, live)

        if config.NOTIFICATION_TYPE == "popup" and not live:
            self._close_popup()
            loading = ResultPopup(anchor=anchor, is_loading=True)
            position = self._user_popup_pos.get(_anchor_key(anchor))
            if position is not None:
                loading.place_at(position)
            self._set_popup(loading)
            self._popup.show()
            QApplication.processEvents()

        if self._worker is not None and self._worker.isRunning():
            logging.debug("Translation running; request %d waits for it.", self._request_seq)
            self._pending_request = request
            return
        self._run_translation(request)

    def _run_translation(self, request) -> None:
        seq, x1, y1, x2, y2, anchor, text_override, live = request
        worker = TranslationWorker(x1, y1, x2, y2, text_override=text_override)
        # Shown unless the user asked for another translation after it: on a fast-changing
        # region every result is newer than the popup's text, so live ones are never dropped
        # just because the next live check has already been queued.
        worker.translation_done.connect(
            lambda src, tr, err: (
                self._on_translation_finished(src, tr, err, anchor, live=live)
                if seq >= self._last_manual_seq
                else logging.debug("Dropped stale translation %d.", seq)
            )
        )
        worker.partial_result.connect(
            lambda partial: self._on_partial_translation(partial) if seq >= self._last_manual_seq else None,
            Qt.QueuedConnection,
        )
        worker.finished.connect(self._on_translation_worker_finished)
        self._replace_worker(worker)
        worker.start()

    def _replace_worker(self, worker) -> None:
        """Make *worker* current; a still-running old one keeps a reference until it ends
        (a running QThread whose last reference goes away aborts the process)."""
        old = self._worker
        if old is not None and old is not worker and old.isRunning():
            self._retired_workers.add(old)
            old.finished.connect(lambda w=old: self._retired_workers.discard(w))
        self._worker = worker

    def _on_translation_worker_finished(self) -> None:
        """Run the request that waited for this translation, if any."""
        request, self._pending_request = self._pending_request, None
        if request is not None:
            self._run_translation(request)

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
        from capture.live_monitor import LiveMonitor, threshold_for

        if hasattr(self, "_live_monitor") and self._live_monitor is not None:
            self._live_monitor.stop()

        interval = int(getattr(config, "LIVE_INTERVAL_SEC", 10) or 10)
        self._live_monitor = LiveMonitor(
            x1,
            y1,
            x2,
            y2,
            interval_sec=interval,
            threshold=threshold_for(getattr(config, "LIVE_SENSITIVITY", "medium")),
        )
        self._live_monitor.region_changed.connect(
            lambda lx1, ly1, lx2, ly2: self._start_translation_pipeline(
                lx1, ly1, lx2, ly2, QRect(lx1, ly1, lx2 - lx1, ly2 - ly1), live=True
            )
        )
        self._live_monitor.start()
        self._main_window.set_monitoring_active(True)

        if self._tray is not None:
            self._tray.act_live_monitor.setChecked(True)
            self._tray.showMessage(
                tr("Живой автомониторинг запущен"),
                tr(
                    "Область автоматически проверяется каждые {seconds} сек.",
                    seconds=int(self._live_monitor.interval_sec),
                ),
                TrayIcon.Information,
                3000,
            )

    def _stop_live_monitoring(self) -> None:
        """D2: Stop live monitor if active."""
        if hasattr(self, "_live_monitor") and self._live_monitor is not None:
            self._live_monitor.stop()
            self._live_monitor = None
            self._main_window.set_monitoring_active(False)
            if self._popup is not None:
                try:
                    self._popup.set_monitoring(False)
                except RuntimeError:
                    pass  # the popup was already deleted
            if self._tray is not None:
                self._tray.act_live_monitor.setChecked(False)
                self._tray.showMessage(
                    tr("Живой мониторинг остановлен"),
                    tr("Автоматическое отслеживание области отключено."),
                    TrayIcon.Information,
                    2000,
                )

    # ── Region Presets ─────────────────────────────────

    def _register_app_hotkeys(self) -> None:
        """(Re)register the translate and settings hotkeys from the current settings."""
        for handle in self._app_hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass  # already gone (e.g. after a pause)
        self._app_hotkey_handles = []
        if self._hotkeys_paused:
            # Saved while its field still has focus: hook it when the capture ends.
            self._tray.refresh_hotkey_labels()
            return
        for hotkey, bridge in ((config.HOTKEY, self._bridge), (config.SETTINGS_HOTKEY, self._settings_bridge)):
            try:
                self._app_hotkey_handles.append(keyboard.add_hotkey(hotkey, bridge.triggered.emit))
            except Exception:
                logging.exception(f"Failed to register global hotkey '{hotkey}'")
        logging.info(f"Registered hotkeys: translate='{config.HOTKEY}', settings='{config.SETTINGS_HOTKEY}'")
        self._tray.refresh_hotkey_labels()

    def _pause_hotkeys(self, capturing: bool) -> None:
        """While a hotkey field is focused, no global hotkey may fire (e.g. the selector)."""
        self._hotkeys_paused = capturing
        if capturing:
            keyboard.unhook_all_hotkeys()
            self._app_hotkey_handles = []
            self._preset_hotkeys.clear()
            logging.debug("Global hotkeys paused for hotkey capture.")
        else:
            self._register_app_hotkeys()
            self._register_preset_hotkeys()

    def _register_preset_hotkeys(self) -> None:
        """Register global keyboard shortcuts for all presets that have a hotkey defined."""
        # Unregister existing preset hotkeys
        for hk in self._preset_hotkeys:
            try:
                keyboard.remove_hotkey(hk)
            except Exception:
                pass
        self._preset_hotkeys.clear()
        self._preset_bridges.clear()

        try:
            from settings.region_presets import load_presets

            presets = load_presets()
        except Exception:
            logging.exception("Failed to load presets for hotkey registration")
            return

        for p in presets:
            hk = p.get("hotkey")
            if not hk:
                continue
            x1, y1 = p.get("x1", 0), p.get("y1", 0)
            x2, y2 = p.get("x2", 0), p.get("y2", 0)
            bridge = HotkeyBridge()
            bridge.triggered.connect(
                lambda _x1=x1, _y1=y1, _x2=x2, _y2=y2: self._on_preset_translate(_x1, _y1, _x2, _y2)
            )
            try:
                keyboard.add_hotkey(hk, bridge.triggered.emit)
                self._preset_hotkeys.append(hk)
                self._preset_bridges.append(bridge)
                logging.info(
                    "Registered preset hotkey '%s' for '%s' (%d,%d)→(%d,%d)", hk, p.get("name"), x1, y1, x2, y2
                )
            except Exception:
                logging.warning("Failed to register preset hotkey '%s'", hk, exc_info=True)

    def _show_presets_dialog(self) -> None:
        """Open the region presets management dialog."""
        try:
            from ui.region_presets_dialog import RegionPresetsDialog

            dlg = RegionPresetsDialog()
            dlg.preset_translate.connect(self._on_preset_translate)
            dlg.request_new_preset.connect(lambda: self._on_new_preset_requested(dlg))
            dlg.presets_updated.connect(self._on_presets_updated)
            self._presets_dialog = dlg
            dlg.exec_()
            self._presets_dialog = None
            self._on_presets_updated()
        except Exception:
            logging.exception("Error showing presets dialog")

    def _on_preset_translate(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Translate the selected preset's region once (from its hotkey or the 'Перевести' button)."""
        anchor = QRect(x1, y1, x2 - x1, y2 - y1)
        if getattr(config, "ENABLE_OCR_PREVIEW", False):
            self._replace_worker(TranslationWorker(x1, y1, x2, y2, ocr_only=True))
            self._worker.ocr_done.connect(lambda text, anc: self._on_ocr_preview_requested(x1, y1, x2, y2, text, anc))
            self._worker.start()
        else:
            self._start_translation_pipeline(x1, y1, x2, y2, anchor=anchor)

    def _on_preset_monitor(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Settings → Regions → "Мониторинг": live monitoring of the selected region."""
        self._start_live_monitoring(x1, y1, x2, y2)

    def _on_presets_updated(self) -> None:
        """Refresh the registered preset hotkeys, the tray menu and Settings → Regions."""
        self._register_preset_hotkeys()
        if self._tray is not None:
            self._tray.rebuild_presets_menu()
        self._main_window.refresh_regions()

    def _add_region(self) -> None:
        """Settings → Regions → "Добавить регион": select an area, then name it."""
        self._presets_dialog = None  # no dialog: the name is asked for on its own
        self._preset_creation_mode = True
        self._show_selector()

    def _on_new_preset_requested(self, dialog) -> None:
        """The user pressed 'Новый' (New) in the presets dialog; start region selection."""
        self._preset_creation_mode = True
        dialog.hide()  # hide dialog while selecting region
        self._show_selector()

    def _on_preset_region_selected(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Handle the selected region while in preset-creation mode."""
        dlg = self._presets_dialog
        if dlg is not None:
            dlg.show()
            dlg.add_new_preset(x1, y1, x2, y2)
        else:
            # Fallback: no dialog reference — open a fresh one
            from PyQt5.QtWidgets import QInputDialog

            from settings.region_presets import save_preset

            name, ok = QInputDialog.getText(
                None,
                tr("Имя пресета"),
                tr("Введите имя для нового пресета региона:"),
            )
            if ok and name.strip():
                try:
                    save_preset(name, x1, y1, x2, y2)
                    logging.info("Preset '%s' saved (no dialog).", name.strip())
                except ValueError as e:
                    logging.warning("Preset save failed: %s", e)
                    from PyQt5.QtWidgets import QMessageBox

                    QMessageBox.warning(None, tr("Ошибка"), str(e))
        self._on_presets_updated()

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
            # The popup body shows the live text; its header keeps "Переводим…".
            try:
                popup.show_partial(partial_text)
            except RuntimeError:
                pass  # popup was deleted between the signal emit and the slot
        except Exception:
            logging.debug("Ignored error in _on_partial_translation", exc_info=True)

    def _on_translation_finished(
        self, source: str, translated: str, error_msg: str, anchor: QRect, *, live: bool = False
    ) -> None:
        try:
            if error_msg:
                logging.warning(f"Translation finished with error: {error_msg}")
                self._show_error(error_msg, anchor, activate=not live)
            else:
                logging.info(
                    f"Translation finished successfully. Source length: {len(source)}, Translated length: {len(translated)}"
                )
                notice = getattr(self._worker, "backend_notice", "") if self._worker is not None else ""
                if notice:
                    logging.warning("Backend notice: %s", notice)
                self._show_result(source, translated, anchor, notice=notice, activate=not live)
            if live and self._popup is not None and getattr(self, "_live_monitor", None) is not None:
                self._popup.set_monitoring(True)  # its header offers "stop monitoring"
        except Exception:
            logging.exception("Error presenting translation result/error popup")

    # ── Popup helpers ────────────────────────────────────

    def _show_result(
        self, source: str, translated: str, anchor: QRect, notice: str = "", activate: bool = True
    ) -> None:
        try:
            from ui.result_popup import show_result

            popup = show_result(
                source,
                translated,
                anchor,
                is_error=False,
                notice=notice,
                tray_icon=self._tray,
                existing_popup=self._popup,
                activate=activate,
                position=self._user_popup_pos.get(_anchor_key(anchor)),
            )
            self._set_popup(popup)
        except Exception:
            logging.exception("Error showing result popup")

    def _show_error(self, message: str, anchor: QRect, activate: bool = True) -> None:
        try:
            from ui.result_popup import show_result

            popup = show_result(
                "",
                message,
                anchor,
                is_error=True,
                tray_icon=self._tray,
                existing_popup=self._popup,
                activate=activate,
                position=self._user_popup_pos.get(_anchor_key(anchor)),
            )
            self._set_popup(popup)
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

    def _set_popup(self, popup) -> None:
        """Make *popup* the current one; it forgets itself only while still current."""
        if popup is not None and popup is not self._popup:
            popup.destroyed.connect(lambda _obj=None, p=popup: self._on_popup_destroyed(p))
            popup.stop_monitoring_clicked.connect(self._stop_live_monitoring)
            key = _anchor_key(popup._anchor)
            if key is not None:
                popup.moved_by_user.connect(lambda pos, k=key: self._user_popup_pos.__setitem__(k, pos))
        self._popup = popup

    def _on_popup_destroyed(self, popup) -> None:
        # A popup closed earlier is destroyed later (deleteLater, fade-out): it must not
        # clear a newer popup that has replaced it in the meantime.
        if self._popup is popup:
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
            self._remove_tray_icon()
            self.app.quit()
        except Exception:
            logging.exception("Error during app shutdown")

    def _restart(self) -> None:
        """Start a fresh copy (it waits for this process to exit), then quit."""
        import subprocess

        args = [a for a in sys.argv[1:] if a != _WAIT_PID_FLAG]
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, *args]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0]), *args]
        cmd += [_WAIT_PID_FLAG, str(os.getpid())]
        try:
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                cmd, creationflags=flags, close_fds=True, cwd=os.path.dirname(os.path.abspath(sys.argv[0]))
            )
            logging.info("Restarting the application...")
        except Exception:
            logging.exception("Failed to start a new instance; not quitting")
            return
        self._quit()

    def _remove_tray_icon(self) -> None:
        """Take the icon off the notification area before the process ends.

        main() ends with os._exit(), which skips the QSystemTrayIcon destructor; a
        hidden-but-alive icon could stay in the tray until the mouse passed over it.
        Exit is clicked inside the tray menu, so close that menu first, then hide and
        destroy the icon (the destructor sends NIM_DELETE) while the event loop runs.
        """
        tray = getattr(self, "_tray", None)
        if tray is None:
            return
        try:
            menu = tray.contextMenu()
            if menu is not None:
                menu.hide()
            tray.hide()
            QApplication.processEvents()
            from PyQt5 import sip

            sip.delete(tray)
        except Exception:
            logging.exception("Failed to remove the tray icon")
        self._tray = None

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


def _set_app_user_model_id() -> None:
    """Own taskbar identity: without it a source run is grouped under python.exe
    and shows Python's icon instead of the window icon."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vrihe.TranslatorOverlay")
    except Exception:
        pass


def main() -> None:
    try:
        _hide_console()
        _set_app_user_model_id()

        app = QApplication(sys.argv)
        from i18n import install_qt_translator
        from ui.theme import apply_app_theme
        from ui.wheel_guard import install_wheel_guard

        apply_app_theme(app)
        # App-wide icon: windows shown before MainWindow (setup wizard, key dialog)
        # have no parent to inherit it from and would get the default Windows one.
        from tray.icon_gen import create_tray_icon

        app.setWindowIcon(create_tray_icon())
        install_wheel_guard(app)
        install_qt_translator(app)

        # Show splash immediately: it covers the remaining init time
        # (MainWindow, TrayIcon, hotkeys).
        splash = _create_splash()
        splash.show()
        app.processEvents()

        # ── First run: how to translate (online / API key / offline model) ─
        from settings.config_manager import first_run_pending

        if first_run_pending():
            logging.info("First launch: showing the setup wizard.")
            splash.close()  # hide splash before interactive dialog
            from ui.setup_wizard import SetupWizard

            if SetupWizard().exec_() != SetupWizard.Accepted:
                logging.info("Setup wizard closed: keeping the defaults.")
                config.FIRST_RUN_DONE = True

        # ── Ask for an LLM key only if the LLM backend has none ─
        from translate.backend import needs_llm_key

        if needs_llm_key():
            logging.info("LLM backend selected without an API key. Prompting first-run dialog.")
            splash.close()  # hide splash before interactive dialog
            from ui.first_run_dialog import FirstRunDialog

            dlg = FirstRunDialog()
            if dlg.exec_() != FirstRunDialog.Accepted:
                logging.info("First-run dialog cancelled. Exiting.")
                sys.exit(0)

        translator = TranslatorApp(app)
        splash.finish(translator._main_window)  # fade out once main window is ready
        code = translator.run()
        # Skip Python finalization: the keyboard library's low-level hook thread and
        # Qt window procedures can still fire while modules are being torn down,
        # which crashed about one exit in three (0xC000041D / access violation).
        # Settings, history and cache are already on disk; the OS frees the rest.
        logging.info(f"Exiting with code {code}.")
        logging.shutdown()
        if sys.stdout is not None:  # None under pythonw
            sys.stdout.flush()
        os._exit(code)
    except Exception:
        logging.exception("Unhandled exception in main()")
        sys.exit(1)


if __name__ == "__main__":
    main()
