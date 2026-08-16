"""
ocr/engine.py — EasyOCR engine with lazy model loading & Cyrillic optimization.

Key features:
  1. Lazy Singleton Reader: Model weights (CRAFT + CRNN) are loaded once into memory
     and reused across all OCR requests.
  2. Thread-safe initialization: double-checked locking prevents concurrent init from
     OcrWarmupWorker and TranslationWorker causing a PyTorch segfault.
  3. Multilingual Support: Default language set is ['ru', 'en'], allowing combined
     recognition of Cyrillic text, English UI elements, usernames, and game slang.
  4. Neural Preprocessing: Optional HSV filter, converts PIL Image to NumPy RGB array.
  5. Line-Ordering & Confidence Thresholding: Filters low-confidence noise and sorts
     detected text blocks top-to-bottom, left-to-right.
  6. Strip-based OCR (1.6): Large images are split into horizontal strips.
     - Strip preprocessing runs in parallel via ThreadPoolExecutor (numpy/PIL ops
       release the GIL, so threads genuinely overlap).
     - Blank strips (low pixel variance) are detected and skipped before OCR.
     - OCR inference itself is sequential: easyocr.Reader.readtext() shares internal
       PyTorch state that is not reentrant from multiple threads simultaneously.
     - Bounding-box Y coordinates are adjusted per strip before results are merged.
     Expected gain: -30–40 % wall time for large sparse images (game UIs, subtitles).
"""

import concurrent.futures
import os
import sys
import logging
import threading
from PIL import Image
import numpy as np

import config

# ── Singleton state ───────────────────────────────────────────────────────────
_reader = None
_reader_lock = threading.Lock()  # guards singleton initialization across QThreads

# ── Strip-mode tuning ─────────────────────────────────────────────────────────
# Images taller than this (px) are split into strips.
_STRIP_MODE_MIN_HEIGHT: int = 400
# Each strip is at most this many pixels tall.
_STRIP_HEIGHT_PX: int = 300
# Grayscale std below this → strip has no text-like content → skip.
_BLANK_STD_THRESHOLD: float = 8.0
# Maximum worker threads for parallel strip preprocessing.
_STRIP_MAX_WORKERS: int = 4


# ── GPU helper ────────────────────────────────────────────────────────────────

def _resolve_gpu(gpu_setting) -> bool:
    """Resolve GPU setting value into a boolean."""
    if isinstance(gpu_setting, bool):
        return gpu_setting
    val = str(gpu_setting).strip().lower()
    if val in ("true", "1"):
        return True
    if val in ("false", "0"):
        return False
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


# ── Singleton reader ──────────────────────────────────────────────────────────

def get_reader():
    """Return the singleton easyocr.Reader instance, initializing it on first use.

    Thread-safe: uses double-checked locking so that OcrWarmupWorker and
    TranslationWorker cannot both initialize easyocr.Reader() simultaneously,
    which would cause a segfault in PyTorch's C++ internals.
    """
    global _reader
    if _reader is None:
        with _reader_lock:       # only one thread enters initialization at a time
            if _reader is None:  # re-check under lock (double-checked locking)
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
                gpu_setting = getattr(config, "EASYOCR_GPU", "auto")
                use_gpu = _resolve_gpu(gpu_setting)

                user_home = os.path.expanduser("~")
                model_storage_dir = os.path.join(user_home, ".EasyOCR", "model")
                os.makedirs(model_storage_dir, exist_ok=True)
                logging.info(
                    f"EasyOCR model storage directory: {model_storage_dir} "
                    f"(GPU={use_gpu}, languages={langs})"
                )

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


# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess(img: Image.Image, scale: int = 1) -> np.ndarray:
    """Enhanced preprocessing for screen OCR: handles thin, small, and low-contrast UI fonts."""
    from PIL import ImageEnhance, ImageFilter, ImageOps

    # 1. Dark theme check & auto-inversion:
    # EasyOCR neural models are trained on dark-on-light text. Inverting dark backgrounds
    # drastically boosts recognition of thin, light UI glyphs like '@', '/', ',', etc.
    gray = img.convert("L")
    is_dark = np.mean(gray) < 128
    if is_dark:
        img = ImageOps.invert(img.convert("RGB"))

    w, h = img.size

    # 2. Add border padding so edge characters/punctuation are not clipped by detector
    pad_px = max(8, min(24, int(min(w, h) * 0.1)))
    fill_color = (255, 255, 255) if is_dark else (0, 0, 0)
    try:
        img = ImageOps.expand(img, border=pad_px, fill=fill_color)
    except Exception:
        img = ImageOps.expand(img, border=pad_px, fill=0)

    w, h = img.size
    effective_scale = scale
    # Auto-upscale small or thin-font crops (height < 250px or width < 500px)
    if effective_scale == 1 and (h < 250 or w < 500):
        effective_scale = 3 if h < 100 else 2

    if effective_scale > 1:
        img = img.resize((w * effective_scale, h * effective_scale), Image.LANCZOS)

    img = img.convert("RGB")

    # 3. Boost contrast for faint/placeholder text
    try:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
        # Subtle sharpening to make thin stroke edges crisp for CRAFT detector
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
    except Exception:
        pass

    if getattr(config, "OCR_USE_HSV_FILTER", False):
        from ocr.hsv_filter import apply_hsv_filter
        img = apply_hsv_filter(img)

    return np.array(img)


# ── Result sorting ────────────────────────────────────────────────────────────

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


_sort_text_results = _sort_results


# ── Strip helpers (1.6) ───────────────────────────────────────────────────────

def _prepare_strip(strip_img: Image.Image, y_offset: int):
    """Pre-process one horizontal strip and check whether it contains any content.

    Returns (img_np, y_offset) when the strip has text-like content, or
    (None, y_offset) when the strip is blank and should be skipped.

    Called from a ThreadPoolExecutor: PIL and numpy operations release the GIL
    so multiple strips are prepared in parallel.
    """
    # Fast blank-detection: compute std of grayscale brightness values.
    # A uniform region (solid background, empty margin) has std ≈ 0–5.
    # Text on any background produces visible contrast (std > threshold).
    gray = np.array(strip_img.convert("L"), dtype=np.float32)
    if gray.std() < _BLANK_STD_THRESHOLD:
        return None, y_offset   # blank strip — skip OCR entirely

    img_np = preprocess(strip_img)
    return img_np, y_offset


def _extract_single(image: Image.Image) -> str:
    """Run OCR on the image as a single piece (small/medium images)."""
    processed = preprocess(image)
    img_np = (
        processed if isinstance(processed, np.ndarray)
        else np.array(processed.convert("RGB"))
    )
    reader = get_reader()
    logging.debug("Calling reader.readtext (single)...")
    results = reader.readtext(
        img_np,
        contrast_ths=0.05,
        adjust_contrast=0.8,
        text_threshold=0.4,
        link_threshold=0.2,
        mag_ratio=1.5,
        add_margin=0.2,
    )
    logging.debug(f"reader.readtext returned {len(results)} raw detections.")

    threshold = getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.20)
    filtered = [r for r in results if r[2] >= threshold]
    logging.debug(f"{len(filtered)} detections met confidence threshold {threshold}.")
    return _sort_results(filtered)


def _extract_strips(image: Image.Image) -> str:
    """Run OCR on a large image split into horizontal strips.

    Pipeline:
      1. Divide the image into strips of _STRIP_HEIGHT_PX pixels.
      2. Pre-process all strips in parallel (ThreadPoolExecutor):
           - Convert to grayscale and measure pixel std.
           - Blank strips (std < _BLANK_STD_THRESHOLD) are discarded here
             without ever calling the neural network.
           - Active strips are converted to RGB numpy arrays for EasyOCR.
      3. Run EasyOCR sequentially on each active strip.
           reader.readtext() uses shared PyTorch model state that is NOT
           safe to call concurrently — parallelism here would cause races
           or crashes.  The benefit is already captured in step 2.
      4. Shift each result's bounding-box Y coordinates by the strip's
         vertical offset so that positions are relative to the full image.
      5. Merge all results and sort top-to-bottom, left-to-right.
    """
    w, h = image.size
    slices = []
    y = 0
    while y < h:
        slices.append((y, min(y + _STRIP_HEIGHT_PX, h)))
        y += _STRIP_HEIGHT_PX

    logging.debug(
        f"OCR strip mode: {len(slices)} strips of ≤{_STRIP_HEIGHT_PX}px "
        f"from {w}×{h} image"
    )

    # ── Step 1–2: Parallel preprocessing + blank detection ────────────────────
    def prep(bounds: tuple[int, int]):
        y1, y2 = bounds
        strip = image.crop((0, y1, w, y2))
        return _prepare_strip(strip, y_offset=y1)

    workers = min(len(slices), _STRIP_MAX_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        prepared = list(pool.map(prep, slices))

    active  = [(arr, off) for arr, off in prepared if arr is not None]
    skipped = len(prepared) - len(active)
    logging.debug(f"Strip preprocessing done: {len(active)} active, {skipped} blank/skipped.")

    if not active:
        return ""

    reader    = get_reader()
    threshold = getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.20)
    all_results: list = []

    for img_np, y_offset in active:
        logging.debug(f"Calling reader.readtext on strip at y={y_offset}...")
        strip_results = reader.readtext(
            img_np,
            contrast_ths=0.05,
            adjust_contrast=0.7,
            text_threshold=0.5,
            link_threshold=0.3,
            mag_ratio=1.4,
            add_margin=0.15,
        )
        logging.debug(f"  → {len(strip_results)} detections in strip y={y_offset}")

        for bbox, text, conf in strip_results:
            if conf < threshold:
                continue
            # Shift each bounding-box point's Y by the strip's vertical offset
            adj_bbox = [[x, y + y_offset] for x, y in bbox]
            all_results.append((adj_bbox, text, conf))

    # ── Step 5: Merge and sort ────────────────────────────────────────────────
    return _sort_results(all_results)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_text(image: Image.Image) -> str:
    """Run EasyOCR on *image* (PIL Image) and return sorted recognised text.

    Automatically selects single-pass or strip mode based on image height:
      • height < _STRIP_MODE_MIN_HEIGHT  → single pass (original behaviour)
      • height ≥ _STRIP_MODE_MIN_HEIGHT  → strip mode (1.6 optimisation)
    """
    logging.debug(f"extract_text called on image of mode {image.mode}, size {image.size}")

    if image.height < _STRIP_MODE_MIN_HEIGHT:
        text = _extract_single(image)
    else:
        text = _extract_strips(image)

    logging.debug(
        f"Extracted OCR text result: '{text[:50]}...'" if len(text) > 50
        else f"Extracted OCR text result: '{text}'"
    )
    return text


def recognise(img: Image.Image, lang: str | None = None) -> str:
    """Run OCR on *img*. Kept as alias to extract_text for backward compatibility."""
    return extract_text(img)
