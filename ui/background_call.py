"""
ui/background_call.py — run a blocking call (key check, update check) off the UI thread.

``run_in_background(fn, on_done, context)`` runs ``fn()`` in a QThread and calls
``on_done(result, error)`` back on the UI thread: exactly one of them is set.
The worker is kept referenced until it finishes (a running QThread that loses its
last reference aborts the process), and ``on_done`` is skipped when *context*
(the widget that asked) was destroyed in the meantime.
"""

from __future__ import annotations

import logging

from PyQt5 import sip
from PyQt5.QtCore import QObject, QThread, pyqtSignal

log = logging.getLogger(__name__)

_running: set = set()


class _CallWorker(QThread):
    done = pyqtSignal(object, object)  # (result, exception)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result, error = self._fn(), None
        except Exception as exc:  # delivered to the UI, which shows it
            result, error = None, exc
        self.done.emit(result, error)


def run_in_background(fn, on_done, context: QObject | None = None) -> QThread:
    """Run *fn* in a worker thread; deliver ``on_done(result, error)`` on the UI thread."""
    worker = _CallWorker(fn)

    def deliver(result, error) -> None:
        if context is not None and sip.isdeleted(context):
            log.debug("Background call finished after its widget was closed: result dropped.")
            return
        on_done(result, error)

    # The worker lives in the UI thread, so the cross-thread emit is queued to it.
    worker.done.connect(deliver)
    _running.add(worker)
    worker.finished.connect(lambda w=worker: _running.discard(w))
    worker.start()
    return worker
