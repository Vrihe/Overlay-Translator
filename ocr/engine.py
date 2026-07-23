"""
ocr/engine.py — EasyOCR engine with lazy model loading & Cyrillic optimization.

Key features:
  1. Lazy Singleton Reader: Model weights (CRAFT + CRNN) are loaded once into memory
     and reused across all OCR requests.
  2. Multilingual Support: Default language set is ['ru', 'en'], allowing combined
     recognition of Cyrillic text, English UI elements, usernames, and game slang.
  3. Neural Preprocessing: Optional HSV filter, converts PIL Image to NumPy RGB array.
  4. Line-Ordering & Confidence Thresholding: Filters low-confidence noise and sorts
     detected text blocks top-to-bottom, left-to-right.
"""

from PIL import Image
import numpy as np

import config

_reader = None


def get_reader():
    """Return the singleton easyocr.Reader instance, initializing it on first use."""
    global _reader
    if _reader is None:
        import easyocr
        langs = getattr(config, "OCR_LANGUAGES", None) or config.EASYOCR_LANGS
        # Resolve GPU mode
        gpu_setting = getattr(config, "EASYOCR_GPU", "auto")
        if isinstance(gpu_setting, bool):
            use_gpu = gpu_setting
        elif str(gpu_setting).strip().lower() in ("true", "1"):
            use_gpu = True
        elif str(gpu_setting).strip().lower() in ("false", "0"):
            use_gpu = False
        else:
            # "auto" — check torch CUDA availability
            try:
                import torch
                use_gpu = torch.cuda.is_available()
            except Exception:
                use_gpu = False
        _reader = easyocr.Reader(langs, gpu=use_gpu, verbose=False)
    return _reader


def preprocess(img: Image.Image) -> Image.Image:
    """Optional preprocessing step for EasyOCR."""
    if getattr(config, "OCR_USE_HSV_FILTER", False):
        from ocr.hsv_filter import apply_hsv_filter
        img = apply_hsv_filter(img)
    return img


def _sort_results(results: list) -> str:
    """Sort EasyOCR results top-to-bottom, left-to-right based on bounding box coordinates.

    Parameters
    ----------
    results : list
        Output from easyocr.readtext: [ (bbox, text, prob), ... ]
        bbox format: [[x0, y0], [x1, y1], [x2, y2], [x3, y3]]

    Returns
    -------
    str
        Extracted text with reading order preserved and lines separated by newline.
    """
    items = []
    for bbox, text, prob in results:
        text_str = text.strip() if isinstance(text, str) else ""
        if not text_str:
            continue
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        center_y = (min_y + max_y) / 2.0
        height = max_y - min_y
        items.append({
            "text": text_str,
            "min_x": min_x,
            "min_y": min_y,
            "center_y": center_y,
            "height": height,
        })

    if not items:
        return ""

    # Sort items by min_y initially
    items.sort(key=lambda i: i["min_y"])

    # Group items into lines based on vertical overlap
    lines = []
    for item in items:
        placed = False
        for line in lines:
            line_avg_center_y = sum(i["center_y"] for i in line) / len(line)
            line_avg_h = sum(i["height"] for i in line) / len(line)
            # Boxes on the same line if vertical distance between centers is small
            if abs(item["center_y"] - line_avg_center_y) < max(8.0, line_avg_h * 0.5):
                line.append(item)
                placed = True
                break
        if not placed:
            lines.append([item])

    # Sort lines top-to-bottom
    lines.sort(key=lambda line: sum(i["center_y"] for i in line) / len(line))

    # Sort items within each line left-to-right
    text_lines = []
    for line in lines:
        line.sort(key=lambda i: i["min_x"])
        text_lines.append(" ".join(i["text"] for i in line))

    return "\n".join(text_lines)


def extract_text(image: Image.Image) -> str:
    """Run EasyOCR on *image* (PIL Image) and return sorted recognized text.

    Parameters
    ----------
    image : PIL.Image.Image
        Source image.

    Returns
    -------
    str
        Extracted text formatted with newline separators.
    """
    processed = preprocess(image)
    img_np = np.array(processed.convert("RGB"))
    reader = get_reader()
    results = reader.readtext(img_np)

    # Filter low-confidence results
    threshold = getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.25)
    filtered = [r for r in results if r[2] >= threshold]

    return _sort_results(filtered)


def recognise(img: Image.Image, lang: str | None = None) -> str:
    """Run OCR on *img*. Kept as alias to extract_text for backward compatibility."""
    return extract_text(img)
