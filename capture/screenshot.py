"""
capture/screenshot.py — grab a screen region as a PIL Image via *mss*.

Multi-monitor aware: uses ``mss.monitors[0]`` (the virtual desktop that
spans all physical monitors) so that global screen coordinates — including
negative ones — are resolved correctly.
"""

from PIL import Image
import mss


def capture_region(x1: int, y1: int, x2: int, y2: int) -> Image.Image:
    """Capture the rectangle (x1, y1)→(x2, y2) in global screen coordinates.

    Coordinates may be negative (e.g. a monitor placed to the left of
    the primary screen).  ``mss`` already understands such coordinates
    when the capture dict uses the same global origin.

    Parameters
    ----------
    x1, y1 : int
        Top-left corner (inclusive).
    x2, y2 : int
        Bottom-right corner (inclusive).

    Returns
    -------
    PIL.Image.Image
        RGB screenshot of the specified region.
    """
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    with mss.mss() as sct:
        # monitors[0] is the virtual desktop encompassing all physical
        # monitors.  Its "left" and "top" can be negative.  By using
        # global coordinates directly in the capture dict, mss will
        # correctly grab across monitor boundaries.
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        raw = sct.grab(monitor)
        # mss returns BGRA; convert to PIL RGB.
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    return img
