"""
capture/live_monitor.py — Background thread for live screen region auto-monitoring.
"""

import logging
import time
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from capture.screenshot import capture_region


class LiveMonitor(QThread):
    """Monitors a specified screen region periodically and emits region_changed when visual content updates."""

    region_changed = pyqtSignal(int, int, int, int)  # (x1, y1, x2, y2)

    def __init__(self, x1: int, y1: int, x2: int, y2: int, interval_sec: float = 2.0, parent=None):
        super().__init__(parent)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.interval_sec = interval_sec
        self._running = True
        self._last_hash: int | None = None

    def run(self) -> None:
        logging.info("LiveMonitor started for bbox (%d, %d, %d, %d)", self.x1, self.y1, self.x2, self.y2)

        while self._running:
            try:
                img = capture_region(self.x1, self.y1, self.x2, self.y2)
                if img:
                    cur_hash = self._compute_phash(img)
                    if self._last_hash is not None and cur_hash != self._last_hash:
                        logging.info("LiveMonitor detected content change in region.")
                        self.region_changed.emit(self.x1, self.y1, self.x2, self.y2)
                    self._last_hash = cur_hash
            except Exception as e:
                logging.warning("LiveMonitor error during region check: %s", e)

            # Sleep in small increments for responsive thread termination
            steps = int(self.interval_sec / 0.2)
            for _ in range(max(1, steps)):
                if not self._running:
                    break
                time.sleep(0.2)

        logging.info("LiveMonitor thread finished.")

    def stop(self) -> None:
        self._running = False
        self.wait()

    @staticmethod
    def _compute_phash(img: Image.Image) -> int:
        """Fast perceptual 64-bit image hash for detecting visual changes."""
        small = img.convert("L").resize((8, 8), Image.Resampling.BILINEAR)
        pixels = list(small.getdata())
        avg = sum(pixels) / 64.0
        return sum(1 << i for i, p in enumerate(pixels) if p > avg)
