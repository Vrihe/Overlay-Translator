"""
ui/nllb_workers.py — background threads for the local NLLB model, shared by the
settings page and the first-run wizard: warm the model up, list the published
builds (HF tags), download one build, download cuBLAS for the GPU. Owners keep a
reference to a running worker until it finishes (a dropped running QThread
aborts the process).
"""

import threading

from PyQt5.QtCore import QThread, pyqtSignal


class NllbPreloadWorker(QThread):
    """Load the local NLLB model off the UI thread so the dialog stays responsive."""

    finished_with_status = pyqtSignal(bool, str)  # (ok, message)

    def run(self) -> None:
        from translate.backend import BACKEND_NLLB, preload

        ok, message = preload(BACKEND_NLLB)
        self.finished_with_status.emit(ok, message)


class NllbVersionsWorker(QThread):
    """Fetch the list of published NLLB builds (HF tags) off the UI thread."""

    finished_with_versions = pyqtSignal(object, str)  # (list[RemoteVersion] | None, error)

    def run(self) -> None:
        from translate.nllb_models import list_remote_versions

        try:
            self.finished_with_versions.emit(list_remote_versions(), "")
        except Exception as e:
            self.finished_with_versions.emit(None, str(e))


class _ProgressMixin:
    """Turns ``(done_bytes, total_bytes)`` callbacks into ``progress_changed`` per percent."""

    def _on_progress(self, done: int, total: int) -> None:
        percent = done * 100 // total if total else 0
        if percent != self._last_percent:
            self._last_percent = percent
            self.progress_changed.emit(percent, done >> 20, total >> 20)


class CudaDownloadWorker(_ProgressMixin, QThread):
    """Download cuBLAS (``translate/cuda_download.py``) so NLLB can use an NVIDIA GPU."""

    progress_changed = pyqtSignal(int, int, int)  # (percent, done MiB, total MiB)
    finished_with_status = pyqtSignal(bool, str)  # (ok, directory | error | "" if cancelled)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancel = threading.Event()
        self._last_percent = -1

    def run(self) -> None:
        from translate.cuda_download import DownloadCancelled, download_cublas

        try:
            path = download_cublas(progress=self._on_progress, cancel=self.cancel)
            self.finished_with_status.emit(True, str(path))
        except DownloadCancelled:
            self.finished_with_status.emit(False, "")
        except Exception as e:
            self.finished_with_status.emit(False, str(e))


class NllbDownloadWorker(_ProgressMixin, QThread):
    """Download one NLLB build from the HF Hub, reporting progress in percent."""

    progress_changed = pyqtSignal(int, int, int)  # (percent, done MiB, total MiB)
    finished_with_status = pyqtSignal(bool, str)  # (ok, model path | error | "" if cancelled)

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.version = version
        self.cancel = threading.Event()
        self._last_percent = -1

    def run(self) -> None:
        from translate.nllb_models import DownloadCancelled, download_version

        try:
            path = download_version(self.version, progress=self._on_progress, cancel=self.cancel)
            self.finished_with_status.emit(True, str(path))
        except DownloadCancelled:
            self.finished_with_status.emit(False, "")
        except Exception as e:
            self.finished_with_status.emit(False, str(e))
