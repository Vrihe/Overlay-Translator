"""
ocr/engine.py — Tesseract OCR with basic image pre-processing.

Pre-processing pipeline (improves accuracy on small / low-contrast text):
  1. Convert to grayscale.
  2. Up-scale 2× with Lanczos resampling.
  3. Boost contrast (factor 1.8).
  4. Sharpen lightly.
"""

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

import config

# Point pytesseract at the Tesseract binary.
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def preprocess(img: Image.Image, scale: int = 2) -> Image.Image:
    """Return a pre-processed copy of *img* optimised for OCR.

    Parameters
    ----------
    img : PIL.Image.Image
        Source screenshot (RGB).
    scale : int
        Up-scale factor (default 2×).

    Returns
    -------
    PIL.Image.Image
        Grayscale, up-scaled, contrast-enhanced image.
    """
    # 1. Grayscale
    img = img.convert("L")

    # 2. Up-scale
    if scale > 1:
        img = img.resize(
            (img.width * scale, img.height * scale),
            Image.LANCZOS,
        )

    # 3. Contrast boost
    img = ImageEnhance.Contrast(img).enhance(1.8)

    # 4. Light sharpening
    img = img.filter(ImageFilter.SHARPEN)

    return img


def recognise(img: Image.Image, lang: str | None = None) -> str:
    """Run Tesseract OCR on *img* and return the recognised text.

    Parameters
    ----------
    img : PIL.Image.Image
        Source screenshot (RGB or L).
    lang : str, optional
        Tesseract language string (e.g. ``"eng"``, ``"eng+rus"``).
        Defaults to ``config.OCR_LANG``.

    Returns
    -------
    str
        Recognised text with leading/trailing whitespace stripped.
    """
    if lang is None:
        lang = config.OCR_LANG

    processed = preprocess(img)

    text: str = pytesseract.image_to_string(processed, lang=lang)
    return text.strip()
