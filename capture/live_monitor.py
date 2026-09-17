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

# Mean absolute difference threshold (0.0 to 255.0) on 64x64 grayscale frames.
# Values > 2.5 filter out cursor blink and subpixel antialiasing while reliably
# detecting new or changed text lines.
_DIFF_THRESHOLD = 2.5


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
        parent=None,
    ):
        super().__init__(parent)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.interval_sec = max(1.0, float(interval_sec))
        self._running = True
        self._last_sig: bytes | None = None

    def run(self) -> None:
        logging.info(
            "LiveMonitor started for bbox (%d, %d, %d, %d) with interval=%.1fs",
            self.x1, self.y1, self.x2, self.y2, self.interval_sec,
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
                        if diff >= _DIFF_THRESHOLD:
                            logging.info(
                                "LiveMonitor detected content change in region (diff=%.2f >= %.2f).",
                                diff, _DIFF_THRESHOLD,
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
        """Downsample image to a compact 64x64 grayscale byte signature."""
        small = img.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
        return small.tobytes()

    @staticmethod
    def _signature_diff(sig1: bytes, sig2: bytes) -> float:
        """Calculate mean absolute pixel difference between two frame signatures."""
        if not sig1 or not sig2 or len(sig1) != len(sig2):
            return 255.0
        return sum(abs(b1 - b2) for b1, b2 in zip(sig1, sig2)) / len(sig1)
