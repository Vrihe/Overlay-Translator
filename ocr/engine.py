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

import os
import sys
import logging
from PIL import Image
import numpy as np

import config

_reader = None


def get_reader():
    """Return the singleton easyocr.Reader instance, initializing it on first use."""
    global _reader
    if _reader is None:
        logging.info("Initializing EasyOCR reader instance...")
        import ctypes

        os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

        if getattr(sys, "frozen", False):
            base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            torch_lib = os.path.join(base_dir, "torch", "lib")
            if os.path.exists(torch_lib):
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(torch_lib)
                    except Exception:
                        pass
                os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")
                for dll_name in [
                    "vcruntime140.dll",
                    "vcruntime140_1.dll",
                    "msvcp140.dll",
                    "vcomp140.dll",
                    "libiomp5md.dll",
                    "asmjit.dll",
                    "fbgemm.dll",
                    "uv.dll",
                    "torch_cpu.dll",
                    "c10.dll",
                    "torch.dll",
                ]:
                    dll_path = os.path.join(torch_lib, dll_name)
                    if os.path.exists(dll_path):
                        try:
                            ctypes.CDLL(dll_path)
                        except Exception:
                            pass

        try:
            import easyocr
            logging.info("easyocr module imported successfully.")
        except Exception:
            logging.exception("Failed to import easyocr module!")
            raise

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

        # Model storage directory: ensure it points to user home ~/.EasyOCR/model
        user_home = os.path.expanduser("~")
        model_storage_dir = os.path.join(user_home, ".EasyOCR", "model")
        os.makedirs(model_storage_dir, exist_ok=True)
        logging.info(f"EasyOCR model storage directory: {model_storage_dir} (GPU={use_gpu}, languages={langs})")

        try:
            _reader = easyocr.Reader(
                langs,
                gpu=use_gpu,
                verbose=False,
                model_storage_directory=model_storage_dir,
            )
            logging.info("EasyOCR reader initialized successfully.")
        except Exception:
            logging.exception("Failed to instantiate easyocr.Reader!")
            raise
    return _reader


def preprocess(img: Image.Image) -> Image.Image:
    """Optional preprocessing step for EasyOCR."""
    if getattr(config, "OCR_USE_HSV_FILTER", False):
        from ocr.hsv_filter import apply_hsv_filter
        img = apply_hsv_filter(img)
    return img


def _sort_results(results: list) -> str:
    """Sort EasyOCR results top-to-bottom, left-to-right based on bounding box coordinates."""
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

    items.sort(key=lambda i: i["min_y"])

    lines = []
    for item in items:
        placed = False
        for line in lines:
            line_avg_center_y = sum(i["center_y"] for i in line) / len(line)
            line_avg_h = sum(i["height"] for i in line) / len(line)
            if abs(item["center_y"] - line_avg_center_y) < max(8.0, line_avg_h * 0.5):
                line.append(item)
                placed = True
                break
        if not placed:
            lines.append([item])

    lines.sort(key=lambda line: sum(i["center_y"] for i in line) / len(line))

    text_lines = []
    for line in lines:
        line.sort(key=lambda i: i["min_x"])
        text_lines.append(" ".join(i["text"] for i in line))

    return "\n".join(text_lines)


def extract_text(image: Image.Image) -> str:
    """Run EasyOCR on *image* (PIL Image) and return sorted recognized text."""
    logging.debug(f"extract_text called on image of mode {image.mode}, size {image.size}")
    processed = preprocess(image)
    img_np = np.array(processed.convert("RGB"))
    reader = get_reader()
    
    logging.debug("Calling reader.readtext...")
    results = reader.readtext(img_np)
    logging.debug(f"reader.readtext returned {len(results)} raw detections.")

    threshold = getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.25)
    filtered = [r for r in results if r[2] >= threshold]
    logging.debug(f"{len(filtered)} detections met confidence threshold {threshold}.")

    text = _sort_results(filtered)
    logging.debug(f"Extracted OCR text result: '{text[:50]}...'" if len(text) > 50 else f"Extracted OCR text result: '{text}'")
    return text


def recognise(img: Image.Image, lang: str | None = None) -> str:
    """Run OCR on *img*. Kept as alias to extract_text for backward compatibility."""
    return extract_text(img)
