"""
capture/live_monitor.py — Background thread for live screen region auto-monitoring.

Polls the target region periodically (default 10s) and emits region_changed
when visual text content updates. Performs an immediate translation on start.
"""

import logging
import time

from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from capture.screenshot import capture_region

# Percent of signature cells whose brightness changed by more than _CELL_DELTA.
# The old metric (mean difference of a 64×64 frame) gave ~0.6 for a new chat line in a
# 320×726 region against a 2.5 threshold, so monitoring never fired on a chat. Measured
# on that region now: a new line ≈ 1 %, a scroll by one line ≈ 1.4 %, a blinking text
# cursor ≈ 0.04 % — "medium" sits well between them.
_DIFF_THRESHOLD = 0.25
_CELL_DELTA = 24
# The signature keeps the region's aspect ratio, about this many cells on its long side.
_SIGNATURE_SIDE = 256

#: Settings → Regions → sensitivity, in percent of changed cells.
SENSITIVITY_THRESHOLDS = {"high": 0.1, "medium": _DIFF_THRESHOLD, "low": 0.6}

#: Settings → Regions → check interval limits, seconds.
MIN_INTERVAL_SEC, MAX_INTERVAL_SEC = 1, 120


def threshold_for(sensitivity: str | None) -> float:
    """Change threshold for a sensitivity setting; unknown values mean "medium"."""
    return SENSITIVITY_THRESHOLDS.get(str(sensitivity or "").lower(), _DIFF_THRESHOLD)


class LiveMonitor(QThread):
    """Monitors a specified screen region periodically and emits region_changed
    when visual content updates.

    Triggers an initial translation immediately upon start, then checks every
    interval_sec (default 10.0s).
    """

    region_changed = pyqtSignal(int, int, int, int)  # (x1, y1, x2, y2)

    def __init__(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        interval_sec: float = 10.0,
        threshold: float = _DIFF_THRESHOLD,
        parent=None,
    ):
        super().__init__(parent)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.interval_sec = min(float(MAX_INTERVAL_SEC), max(float(MIN_INTERVAL_SEC), float(interval_sec)))
        self.threshold = float(threshold)
        self._running = True
        self._last_sig: bytes | None = None

    def run(self) -> None:
        logging.info(
            "LiveMonitor started for bbox (%d, %d, %d, %d) with interval=%.1fs, threshold=%.1f",
            self.x1,
            self.y1,
            self.x2,
            self.y2,
            self.interval_sec,
            self.threshold,
        )

        # ── Step 1: Immediate initial translation ────────────────
        try:
            img = capture_region(self.x1, self.y1, self.x2, self.y2)
            if img:
                self._last_sig = self._compute_signature(img)
            self.region_changed.emit(self.x1, self.y1, self.x2, self.y2)
        except Exception as e:
            logging.warning("LiveMonitor error during initial region check: %s", e)

        # ── Step 2: Periodic polling loop ────────────────────────
        while self._running:
            # Sleep in small increments for responsive thread termination
            steps = max(1, int(self.interval_sec / 0.2))
            for _ in range(steps):
                if not self._running:
                    break
                time.sleep(0.2)

            if not self._running:
                break

            try:
                img = capture_region(self.x1, self.y1, self.x2, self.y2)
                if img:
                    cur_sig = self._compute_signature(img)
                    if self._last_sig is not None:
                        diff = self._signature_diff(cur_sig, self._last_sig)
                        if diff >= self.threshold:
                            logging.info(
                                "LiveMonitor detected content change in region (diff=%.2f >= %.2f).",
                                diff,
                                self.threshold,
                            )
                            self.region_changed.emit(self.x1, self.y1, self.x2, self.y2)
                            self._last_sig = cur_sig
                    else:
                        self._last_sig = cur_sig
            except Exception as e:
                logging.warning("LiveMonitor error during periodic region check: %s", e)

        logging.info("LiveMonitor thread finished.")

    def stop(self) -> None:
        """Signal thread to stop and wait for it to exit."""
        self._running = False
        self.wait()

    @staticmethod
    def _compute_signature(img: Image.Image) -> bytes:
        """Grayscale thumbnail (aspect kept, ~_SIGNATURE_SIDE cells on the long side)."""
        w, h = img.size
        factor = max(1, round(max(w, h) / _SIGNATURE_SIDE))
        small = img.convert("L").resize((max(1, w // factor), max(1, h // factor)), Image.Resampling.BILINEAR)
        return small.tobytes()

    @staticmethod
    def _signature_diff(sig1: bytes, sig2: bytes) -> float:
        """Percent of cells that changed by more than _CELL_DELTA (100 when incomparable)."""
        if not sig1 or not sig2 or len(sig1) != len(sig2):
            return 100.0
        changed = sum(abs(b1 - b2) > _CELL_DELTA for b1, b2 in zip(sig1, sig2))
        return 100.0 * changed / len(sig1)
