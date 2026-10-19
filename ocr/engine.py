"""
ocr/engine.py — RapidOCR (PP-OCR on ONNX Runtime) engine with lazy model loading.

Key features:
  1. Lazy Singleton Engine: the det + rec ONNX sessions are created once and reused
     across all OCR requests.
  2. Thread-safe initialization: double-checked locking prevents OcrWarmupWorker and
     TranslationWorker from building two engines at once; a second lock serialises
     inference (one session is not run from several threads at the same time).
  3. Cyrillic + Latin: the PP-OCRv5 "eslav" recognition model reads Russian,
     Ukrainian and Belarusian together with English UI elements and game slang.
  4. GPU via DirectML (onnxruntime-directml): any DirectX 12 GPU, no CUDA needed.
     A GPU failure mid-inference rebuilds the engine on the CPU and retries.
  5. Preprocessing: optional HSV filter, converts PIL Image to NumPy RGB array.
  6. Line-Ordering & Confidence Thresholding: filters low-confidence noise and sorts
     detected text blocks top-to-bottom, left-to-right.
  7. Strip-based OCR (1.6): Large images are split into horizontal strips.
     - Strip preprocessing runs in parallel via ThreadPoolExecutor (numpy/PIL ops
       release the GIL, so threads genuinely overlap).
     - Blank strips (low pixel variance) are detected and skipped before OCR.
     - OCR inference itself is sequential (see the inference lock above).
     - Bounding-box Y coordinates are adjusted per strip before results are merged.

Models live in <user data dir>/ocr_models.  Files shipped inside the rapidocr
package (and the rec model bundled by the build) are copied there on first use;
anything still missing is downloaded once by rapidocr.
"""

import concurrent.futures
import logging
import os
import shutil
import threading
from pathlib import Path

from PIL import Image
import numpy as np

import config

# ── Singleton state ───────────────────────────────────────────────────────────
_reader = None
_reader_lock = threading.Lock()  # guards singleton initialization across QThreads
_infer_lock = threading.Lock()   # serialises inference on the shared engine

# Track whether the current engine runs on the GPU (for the CPU fallback).
_reader_on_gpu: bool = False

# ── Strip-mode tuning ─────────────────────────────────────────────────────────
# Images taller than this (px) are split into strips.
_STRIP_MODE_MIN_HEIGHT: int = 400
# Each strip is at most this many pixels tall.
_STRIP_HEIGHT_PX: int = 300
# Grayscale std below this → strip has no text-like content → skip.
_BLANK_STD_THRESHOLD: float = 8.0
# Maximum worker threads for parallel strip preprocessing.
_STRIP_MAX_WORKERS: int = 4

# ── Models ────────────────────────────────────────────────────────────────────
# OCR language codes that the East-Slavic recognition model covers.
_CYRILLIC_LANGS = {"ru", "uk", "be"}
# Model files the engine can use (keep in sync with _OCR_MODELS in build_deps.spec).
_MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "eslav_PP-OCRv5_rec_mobile.onnx",
    "en_PP-OCRv5_rec_mobile.onnx",
)


# ── GPU helpers ───────────────────────────────────────────────────────────────

_ort_import_error: Exception | None = None


def _onnxruntime():
    """Import onnxruntime once; a failed DLL init is never retried.

    Re-importing after "DLL initialization routine failed" (e.g. onnxruntime loaded
    after PyQt5's old msvcp140.dll, see main.py) can crash the process later.
    """
    global _ort_import_error
    if _ort_import_error is not None:
        raise ImportError("onnxruntime is unavailable") from _ort_import_error
    try:
        import onnxruntime
    except Exception as exc:
        _ort_import_error = exc
        logging.exception("onnxruntime failed to load")
        raise
    return onnxruntime


def _dml_available() -> bool:
    """Return True if onnxruntime ships the DirectML execution provider."""
    try:
        return "DmlExecutionProvider" in _onnxruntime().get_available_providers()
    except Exception:
        return False


def _resolve_gpu(gpu_setting) -> bool:
    """Resolve GPU setting value into a boolean (legacy .env support)."""
    if isinstance(gpu_setting, bool):
        return gpu_setting
    val = str(gpu_setting).strip().lower()
    if val in ("true", "1"):
        return True
    if val in ("false", "0"):
        return False
    return _dml_available()


def _should_use_gpu() -> bool:
    """Decide whether to run OCR on the GPU through DirectML.

    Reads ``config.OCR_GPU_MODE`` (from settings.json):
      • ``"gpu"`` / ``"auto"`` — use DirectML when it is available, else the CPU.
      • ``"cpu"``              — never use the GPU.

    Also respects the legacy ``EASYOCR_GPU`` env-var / .env override.
    """
    legacy = str(getattr(config, "EASYOCR_GPU", "auto")).strip().lower()
    if legacy in ("true", "1"):
        return _dml_available()
    if legacy in ("false", "0"):
        return False

    mode = str(getattr(config, "OCR_GPU_MODE", "auto")).strip().lower()
    if mode == "cpu":
        return False
    return _dml_available()


# ── Model files ───────────────────────────────────────────────────────────────

def _model_dir() -> Path:
    """Writable model directory, seeded from the models shipped with rapidocr."""
    target = Path(config.USER_DATA_DIR) / "ocr_models"
    target.mkdir(parents=True, exist_ok=True)
    try:
        import rapidocr
        bundled = Path(rapidocr.__file__).parent / "models"
        for name in _MODEL_FILES:
            src, dst = bundled / name, target / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
    except Exception:
        logging.exception("Could not copy bundled OCR models to %s", target)
    return target


def _rec_lang(langs):
    """Pick the recognition model language for the configured OCR languages."""
    from rapidocr import LangRec

    codes = {str(code).strip().lower() for code in (langs or [])}
    if codes & _CYRILLIC_LANGS or not codes:
        return LangRec.ESLAV
    return LangRec.EN


def _build_engine(use_gpu: bool):
    """Create a RapidOCR engine (PP-OCRv6 det + PP-OCRv5 rec, no angle classifier)."""
    _onnxruntime()  # fail cleanly before rapidocr touches a broken onnxruntime
    from rapidocr import ModelType, OCRVersion, RapidOCR

    langs = getattr(config, "OCR_LANGUAGES", None) or config.EASYOCR_LANGS
    rec_lang = _rec_lang(langs)
    model_dir = _model_dir()

    # Limit CPU threads so OCR doesn't starve the game of cores.
    cpu_count = os.cpu_count() or 4
    max_threads = max(2, min(4, cpu_count // 2))

    logging.info(
        "Initializing RapidOCR engine (DirectML=%s, rec=%s, threads=%d / %d, models=%s)",
        use_gpu, rec_lang.value, max_threads, cpu_count, model_dir,
    )
    return RapidOCR(params={
        "Global.log_level": "warning",
        "Global.model_root_dir": str(model_dir),
        # Screen text is never upside down: skip the angle classifier.
        "Global.use_cls": False,
        "Global.text_score": float(getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.25)),
        "EngineConfig.onnxruntime.use_dml": use_gpu,
        "EngineConfig.onnxruntime.intra_op_num_threads": max_threads,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.lang_type": rec_lang,
        "Rec.model_type": ModelType.MOBILE,
    })


# ── Singleton reader ──────────────────────────────────────────────────────────

def get_reader():
    """Return the singleton RapidOCR engine, initializing it on first use.

    Thread-safe: uses double-checked locking so that OcrWarmupWorker and
    TranslationWorker cannot both build the engine simultaneously.
    """
    global _reader, _reader_on_gpu
    if _reader is None:
        with _reader_lock:       # only one thread enters initialization at a time
            if _reader is None:  # re-check under lock (double-checked locking)
                use_gpu = _should_use_gpu()
                try:
                    _reader = _build_engine(use_gpu)
                    _reader_on_gpu = use_gpu
                    logging.info("RapidOCR engine initialized successfully (DirectML=%s).", use_gpu)
                except Exception:
                    logging.exception("Failed to initialize the RapidOCR engine!")
                    raise
    return _reader


def warm_up() -> None:
    """Build the engine and run one tiny inference.

    The first DirectML run compiles GPU kernels (~2 s); doing it here keeps that
    cost off the user's first hotkey press.
    """
    from PIL import ImageDraw

    img = Image.new("RGB", (240, 48), "white")
    ImageDraw.Draw(img).text((10, 14), "Warm up 123", fill="black", font_size=20)
    _safe_readtext(get_reader(), np.array(img))


def _fallback_to_cpu() -> None:
    """Replace a failing GPU engine with a CPU one for the rest of the session."""
    global _reader, _reader_on_gpu
    with _reader_lock:
        if _reader_on_gpu:
            _reader = _build_engine(use_gpu=False)
            _reader_on_gpu = False


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


def _to_results(output) -> list:
    """Convert a RapidOCROutput into [(bbox, text, score), …] (bbox = 4 [x, y] points)."""
    if output is None or output.boxes is None or output.txts is None:
        return []
    return [
        (box.tolist(), text, float(score))
        for box, text, score in zip(output.boxes, output.txts, output.scores)
    ]


def _safe_readtext(reader, img_np) -> list:
    """Run OCR on *img_np* with an automatic fallback to the CPU.

    If DirectML fails mid-inference (device removed, driver reset, a game
    suddenly taking all VRAM), the engine is rebuilt on the CPU and the same
    frame is re-run, so the user still gets a result.
    """
    try:
        with _infer_lock:
            return _to_results(reader(img_np))
    except Exception:
        if not _reader_on_gpu:
            raise
        logging.warning("GPU (DirectML) OCR failed — switching to CPU", exc_info=True)
    try:
        _fallback_to_cpu()
        with _infer_lock:
            return _to_results(get_reader()(img_np))
    except Exception:
        logging.exception("CPU fallback also failed")
        return []


def _filter_confident(results: list) -> list:
    threshold = getattr(config, "EASYOCR_CONFIDENCE_THRESHOLD", 0.25)
    return [r for r in results if r[2] >= threshold]


def _extract_single(image: Image.Image) -> str:
    """Run OCR on the image as a single piece (small/medium images)."""
    processed = preprocess(image)
    img_np = (
        processed if isinstance(processed, np.ndarray)
        else np.array(processed.convert("RGB"))
    )
    reader = get_reader()
    logging.debug("Running OCR (single pass)...")
    results = _safe_readtext(reader, img_np)
    logging.debug(f"OCR returned {len(results)} raw detections.")

    filtered = _filter_confident(results)
    logging.debug(f"{len(filtered)} detections met the confidence threshold.")
    return _sort_results(filtered)


def _extract_strips(image: Image.Image) -> str:
    """Run OCR on a large image split into horizontal strips.

    Pipeline:
      1. Divide the image into strips of _STRIP_HEIGHT_PX pixels.
      2. Pre-process all strips in parallel (ThreadPoolExecutor):
           - Convert to grayscale and measure pixel std.
           - Blank strips (std < _BLANK_STD_THRESHOLD) are discarded here
             without ever calling the neural network.
           - Active strips are converted to RGB numpy arrays.
      3. Run OCR sequentially on each active strip (inference is serialised
         by _infer_lock; the benefit is already captured in step 2).
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

    reader = get_reader()
    all_results: list = []

    for img_np, y_offset in active:
        logging.debug(f"Running OCR on strip at y={y_offset}...")
        strip_results = _filter_confident(_safe_readtext(reader, img_np))
        logging.debug(f"  → {len(strip_results)} detections in strip y={y_offset}")

        for bbox, text, conf in strip_results:
            # Shift each bounding-box point's Y by the strip's vertical offset
            adj_bbox = [[x, y + y_offset] for x, y in bbox]
            all_results.append((adj_bbox, text, conf))

    # ── Step 5: Merge and sort ────────────────────────────────────────────────
    return _sort_results(all_results)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_text(image: Image.Image) -> str:
    """Run OCR on *image* (PIL Image) and return sorted recognised text.

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
