"""
tests/test_worker_lifetime.py — a main-window worker whose result slot drops the last
reference while run() is still returning stays alive until it finishes (dropping a
running QThread aborts the process with 0xc0000409).
"""

import sys
import time
import unittest

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication

from ui import main_window

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class _Worker(QThread):
    done = pyqtSignal()

    def run(self):
        self.done.emit()
        time.sleep(0.05)  # still running when the slot drops its reference


class TestKeepUntilFinished(unittest.TestCase):
    def test_worker_survives_its_result_slot(self):
        holder = {"worker": _Worker()}
        worker = holder["worker"]
        worker.done.connect(lambda: holder.pop("worker", None))
        main_window._keep_until_finished(worker)
        worker.start()
        worker_id = id(worker)
        del worker

        def parked():
            return any(id(w) == worker_id for w in main_window._running_workers)

        deadline = time.monotonic() + 5
        while parked() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        self.assertEqual(holder, {})
        self.assertFalse(parked())


if __name__ == "__main__":
    unittest.main()
