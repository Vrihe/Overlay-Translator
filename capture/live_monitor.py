"""
capture/live_monitor.py — Background thread for live screen region auto-monitoring.
"""

import logging
import time
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from capture.screenshot import capture_region

# Hamming distance threshold for perceptual hash comparison.
# Hashes differing by <= PHASH_THRESHOLD bits are considered visually identical,
# filtering out cursor blink, minor animations, and rendering noise (~3 bits).
_PHASH_THRESHOLD = 3

# Adaptive interval bounds (seconds).
_INTERVAL_MIN = 0.5   # used right after a detected change (active content)
_INTERVAL_MAX = 5.0   # used during long static periods (idle)
_INTERVAL_BACKOFF = 1.5  # multiplier applied each cycle with no change


class LiveMonitor(QThread):
    """Monitors a specified screen region periodically and emits region_changed when visual content updates.

    Adaptive polling: interval ramps from 0.5s to 5.0s while the region is static,
    then resets to 0.5s as soon as a change is detected.
    pHash comparison uses Hamming distance (threshold=3 bits) to ignore rendering noise.
    """

    region_changed = pyqtSignal(int, int, int, int)  # (x1, y1, x2, y2)

    def __init__(self, x1: int, y1: int, x2: int, y2: int, interval_sec: float = 2.0, parent=None):
        super().__init__(parent)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.interval_sec = interval_sec  # kept for API compatibility; used as initial interval
        self._running = True
        self._last_hash: int | None = None

    def run(self) -> None:
        logging.info("LiveMonitor started for bbox (%d, %d, %d, %d)", self.x1, self.y1, self.x2, self.y2)

        interval = min(self.interval_sec, _INTERVAL_MIN)

        while self._running:
            changed = False
            try:
                img = capture_region(self.x1, self.y1, self.x2, self.y2)
                if img:
                    cur_hash = self._compute_phash(img)
                    if self._last_hash is not None:
                        dist = self._hamming(cur_hash, self._last_hash)
                        if dist > _PHASH_THRESHOLD:
                            logging.info(
                                "LiveMonitor detected content change in region (hamming=%d).", dist
                            )
                            self.region_changed.emit(self.x1, self.y1, self.x2, self.y2)
                            changed = True
                    self._last_hash = cur_hash
            except Exception as e:
                logging.warning("LiveMonitor error during region check: %s", e)

            # Adaptive interval: reset on change, apply backoff on static screen
            if changed:
                interval = _INTERVAL_MIN
            else:
                interval = min(interval * _INTERVAL_BACKOFF, _INTERVAL_MAX)

            # Sleep in small increments for responsive thread termination
            steps = max(1, int(interval / 0.2))
            for _ in range(steps):
                if not self._running:
                    break
                time.sleep(0.2)

        logging.info("LiveMonitor thread finished.")

    def stop(self) -> None:
        self._running = False
        self.wait()

    @staticmethod
    def _hamming(h1: int, h2: int) -> int:
        """Count differing bits between two 64-bit perceptual hashes."""
        return bin(h1 ^ h2).count('1')

    @staticmethod
    def _compute_phash(img: Image.Image) -> int:
        """Fast perceptual 64-bit image hash for detecting visual changes."""
        small = img.convert("L").resize((8, 8), Image.Resampling.BILINEAR)
        pixels = list(small.getdata())
        avg = sum(pixels) / 64.0
        return sum(1 << i for i, p in enumerate(pixels) if p > avg)
