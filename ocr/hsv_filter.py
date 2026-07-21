"""
ocr/hsv_filter.py — optional HSV-based preprocessing for OCR.

Useful for extracting text from coloured or gradient backgrounds:
  1. Convert RGB → HSV.
  2. Extract the Value (brightness) channel.
  3. Apply a simple threshold to produce a clean binary image.

Enable via ``config.OCR_USE_HSV_FILTER = True``.
"""

from PIL import Image


def apply_hsv_filter(img: Image.Image, threshold: int = 128) -> Image.Image:
    """Convert *img* to an HSV-based binary image optimised for OCR.

    Parameters
    ----------
    img : PIL.Image.Image
        Source screenshot (RGB).
    threshold : int
        Pixel values above this in the V channel become white;
        below become black.  128 is a reasonable default.

    Returns
    -------
    PIL.Image.Image
        Grayscale (mode ``"L"``) binary image.
    """
    # Ensure RGB input.
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Convert to HSV and extract the V (brightness) channel.
    hsv = img.convert("HSV")
    _h, _s, v = hsv.split()

    # Simple global threshold (Otsu-like results without numpy).
    binary = v.point(lambda px: 255 if px >= threshold else 0, mode="L")

    return binary
