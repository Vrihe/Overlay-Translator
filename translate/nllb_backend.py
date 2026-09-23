"""
translate/nllb_backend.py — offline translation via a quantized NLLB-200 model.

Mirrors the public surface of ``translate.llm_client`` so the two are
interchangeable behind ``translate.backend``:

    translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None) -> str
    detect_and_translate(text, target_lang=None, domain_id=None, on_chunk=None) -> (lang, text)
    reset_client() -> None

Runtime dependencies are only ``ctranslate2`` + ``sentencepiece``; the model is
a CTranslate2 int8 build produced by ``ct2-transformers-converter`` (see
``scripts/test_nllb_translation.py`` and docs in ARCHITECTURE.md).

Loading is **lazy**: the ~620 MB model is touched on the first real translation
request, never at import time and never at application startup.

Differences from the API backend, by design:
  • Domain profiles carry prompts and few-shot examples, which a seq2seq NMT
    model cannot consume. ``domain_id`` therefore only namespaces the cache.
  • Streaming is not supported by CTranslate2 beam search; *on_chunk* is called
    once with the final text so the UI behaves consistently.
  • Cache entries are written under ``"<domain_id>|nllb"`` so local output never
    contaminates the API-produced history used for fine-tuning datasets.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import config
from cache.store import get_cached, save_to_cache

_logger = logging.getLogger("translator.nllb")

# ── Errors ───────────────────────────────────────────────


class NllbError(RuntimeError):
    """Base class for local-backend failures."""


class NllbModelUnavailable(NllbError):
    """Model directory missing, incomplete, or failed to load.

    This is an *infrastructure* failure: the dispatcher falls back to the API
    backend and notifies the user (see ``translate/backend.py``).
    """


class NllbTranslationError(NllbError):
    """The model is loaded but this particular translation failed.

    Surfaced to the user as an explicit error — no silent API fallback.
    """


class _CudaUnavailable(Exception):
    """GPU inference cannot be used; the backend falls back to the CPU.

    *notify* is False when the fallback is expected (auto mode on a machine
    without an NVIDIA GPU) and should only be logged, not shown to the user.
    """

    def __init__(self, reason: str, *, notify: bool) -> None:
        super().__init__(reason)
        self.notify = notify


# ── Language codes ───────────────────────────────────────
# ISO 639-1 → FLORES-200 code used by NLLB-200.
# Covers every language offered in ui/settings_dialog._SOURCE_LANGUAGES /
# _TARGET_LANGUAGES plus the Central/Eastern-European set targeted by the
# fine-tuning work (en/de/fr/es/ru/uk/be/pl/cs/hu).

NLLB_LANG_CODES: dict[str, str] = {
    "en": "eng_Latn",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "be": "bel_Cyrl",
    "pl": "pol_Latn",
    "cs": "ces_Latn",
    "hu": "hun_Latn",
    "sk": "slk_Latn",
    "bg": "bul_Cyrl",
    "ro": "ron_Latn",
    "tr": "tur_Latn",
    "ar": "arb_Arab",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "nl": "nld_Latn",
    "sv": "swe_Latn",
    "fi": "fin_Latn",
    "el": "ell_Grek",
    "he": "heb_Hebr",
    "vi": "vie_Latn",
    "th": "tha_Thai",
    "hi": "hin_Deva",
    "id": "ind_Latn",
}

SUPPORTED_LANGS = frozenset(NLLB_LANG_CODES)

# ── Model discovery ──────────────────────────────────────

MODEL_DIRNAME = "nllb-200-ct2-int8"

#: Files a usable CTranslate2 NLLB build must contain.
_REQUIRED_FILES = ("model.bin", "config.json", "shared_vocabulary.json",
                   "sentencepiece.bpe.model")


def explicit_model_dir() -> Path | None:
    """Return the user-configured model directory, or None when unset.

    A configured path wins outright: if it is wrong we say so instead of quietly
    loading some other copy of the model from a default location.
    """
    configured = (getattr(config, "NLLB_MODEL_PATH", "") or "").strip()
    if configured:
        return Path(configured)

    env_dir = (os.environ.get("NLLB_MODEL_DIR") or "").strip()
    if env_dir:
        return Path(env_dir)

    return None


def _auto_model_dirs() -> list[Path]:
    """Default locations searched when no explicit path is configured."""
    candidates = [
        Path(config._PROJECT_DIR) / "models" / MODEL_DIRNAME,
        Path(config.USER_DATA_DIR) / "models" / MODEL_DIRNAME,
        Path(r"D:\projects\overlay-translator\models") / MODEL_DIRNAME,
    ]

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _is_complete(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in _REQUIRED_FILES)


def missing_files(path: Path) -> list[str]:
    """Names of the required files absent from *path*."""
    return [name for name in _REQUIRED_FILES if not (path / name).is_file()]


def resolve_model_dir() -> Path | None:
    """Return the model directory to use, or None if no usable one exists.

    An explicitly configured path is authoritative — no silent fallback to the
    auto-discovery locations.
    """
    explicit = explicit_model_dir()
    if explicit is not None:
        return explicit if _is_complete(explicit) else None

    for path in _auto_model_dirs():
        if _is_complete(path):
            return path
    return None


def describe_model_location() -> str:
    """Human-readable status of the local model, for the settings UI."""
    explicit = explicit_model_dir()
    if explicit is not None:
        if _is_complete(explicit):
            return f"Модель найдена: {explicit}"
        if explicit.is_dir():
            return (
                f"Указанный каталог {explicit} не содержит модель — "
                "отсутствуют файлы: " + ", ".join(missing_files(explicit))
            )
        return f"Указанный каталог не существует: {explicit}"

    found = resolve_model_dir()
    if found is not None:
        return f"Модель найдена: {found}"
    searched = "\n".join(f"  • {p}" for p in _auto_model_dirs())
    return "Модель не найдена. Искали в:\n" + searched


# ── Backend ──────────────────────────────────────────────


#: Accepted values for the ``device`` argument and the ``NLLB_DEVICE`` env var.
DEVICES = ("auto", "cuda", "cpu")


class NllbBackend:
    """Lazily-loaded CTranslate2 NLLB translator with the llm_client interface.

    ``device="auto"`` (the default) uses an NVIDIA GPU when one is present and
    cuBLAS can be found (see ``translate/cuda_support.py``), and the CPU
    otherwise. Any CUDA failure falls back to the CPU instead of raising.
    """

    def __init__(
        self,
        model_dir: str | Path | None = None,
        *,
        device: str | None = None,
        compute_type: str = "int8",
        gpu_compute_type: str = "int8_float16",
        intra_threads: int | None = None,
        beam_size: int = 4,
    ) -> None:
        self._explicit_dir = Path(model_dir) if model_dir else None
        requested = (device or os.environ.get("NLLB_DEVICE") or "auto").strip().lower()
        if requested not in DEVICES:
            _logger.warning("Unknown NLLB device %r, using 'auto'", requested)
            requested = "auto"
        self._device = requested
        self._compute_type = compute_type
        self._gpu_compute_type = gpu_compute_type
        self._intra_threads = intra_threads or min(4, os.cpu_count() or 4)
        self._beam_size = beam_size

        self._translator = None
        self._sp = None
        self._model_dir: Path | None = None
        self._load_seconds: float = 0.0
        self._active_device: str = ""
        self._cuda_fallback_reason: str = ""
        self._pending_notice: str = ""
        self._load_lock = threading.Lock()
        self._inflight = 0
        self._inflight_lock = threading.Lock()

    # ── State ────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None and self._sp is not None

    @property
    def model_dir(self) -> Path | None:
        return self._model_dir

    @property
    def load_seconds(self) -> float:
        """Wall time the last successful load took, in seconds."""
        return self._load_seconds

    @property
    def active_device(self) -> str:
        """Device the loaded model runs on ("cuda" or "cpu"); "" when not loaded."""
        return self._active_device

    @property
    def cuda_fallback_reason(self) -> str:
        """Why CUDA was not used on the last load; "" when it was, or was not tried."""
        return self._cuda_fallback_reason

    def take_notice(self) -> str:
        """Return and clear the one-shot user notice left by the last load."""
        notice, self._pending_notice = self._pending_notice, ""
        return notice

    # ── Loading ──────────────────────────────────────────

    def ensure_loaded(self) -> None:
        """Load the model if it is not loaded yet.

        Raises
        ------
        NllbModelUnavailable
            If the model cannot be found or cannot be initialised.
        """
        if self.is_loaded:
            return

        with self._load_lock:
            if self.is_loaded:  # another thread won the race
                return

            model_dir = self._explicit_dir if self._explicit_dir else resolve_model_dir()
            if model_dir is None:
                raise NllbModelUnavailable(
                    "Локальная модель NLLB не найдена.\n"
                    + describe_model_location()
                    + "\n\nУкажите путь в Настройках или сконвертируйте модель командой "
                      "ct2-transformers-converter (см. scripts/test_nllb_translation.py)."
                )
            if not _is_complete(model_dir):
                raise NllbModelUnavailable(
                    f"Каталог модели {model_dir} неполон — отсутствуют файлы: "
                    + ", ".join(missing_files(model_dir))
                )

            try:
                import ctranslate2
                import sentencepiece as spm
            except ImportError as exc:
                raise NllbModelUnavailable(
                    "Не установлены пакеты для локального перевода. "
                    "Выполните: pip install ctranslate2 sentencepiece"
                ) from exc

            t0 = time.perf_counter()
            translator, device, compute_type = self._create_translator(ctranslate2, model_dir)
            try:
                sp = spm.SentencePieceProcessor(
                    model_file=str(model_dir / "sentencepiece.bpe.model")
                )
            except Exception as exc:
                raise NllbModelUnavailable(
                    f"Не удалось загрузить локальную модель из {model_dir}: {exc}"
                ) from exc

            self._translator = translator
            self._sp = sp
            self._model_dir = model_dir
            self._active_device = device
            self._load_seconds = time.perf_counter() - t0
            _logger.info(
                "NLLB loaded from %s in %.2fs (device=%s, compute=%s, threads=%d)",
                model_dir, self._load_seconds, device, compute_type, self._intra_threads,
            )

    def _create_translator(self, ctranslate2, model_dir: Path):
        """Create the CTranslate2 translator on the best usable device.

        Returns ``(translator, device, compute_type)``. CUDA problems never
        propagate: they are logged, recorded for the UI, and the CPU is used.
        """
        self._cuda_fallback_reason = ""
        if self._device in ("auto", "cuda"):
            try:
                translator = self._create_cuda_translator(ctranslate2, model_dir)
                return translator, "cuda", self._gpu_compute_type
            except _CudaUnavailable as exc:
                self._cuda_fallback_reason = str(exc)
                if exc.notify:
                    _logger.warning("CUDA unavailable, using CPU inference: %s", exc)
                    first_line = str(exc).splitlines()[0]
                    self._pending_notice = f"CUDA unavailable, using CPU inference ({first_line})"
                else:
                    _logger.info("CUDA not used, running NLLB on CPU: %s", exc)

        try:
            translator = ctranslate2.Translator(
                str(model_dir),
                device="cpu",
                compute_type=self._compute_type,
                inter_threads=1,
                intra_threads=self._intra_threads,
            )
        except Exception as exc:
            raise NllbModelUnavailable(
                f"Не удалось загрузить локальную модель из {model_dir}: {exc}"
            ) from exc
        return translator, "cpu", self._compute_type

    def _create_cuda_translator(self, ctranslate2, model_dir: Path):
        """Create a GPU translator and prove it works, or raise ``_CudaUnavailable``."""
        from translate.cuda_support import cublas_missing_hint, prepare_cuda_libraries

        explicit = self._device == "cuda"
        try:
            gpu_count = ctranslate2.get_cuda_device_count()
        except Exception as exc:
            raise _CudaUnavailable(f"CUDA query failed: {exc}", notify=explicit) from exc
        if gpu_count == 0:
            raise _CudaUnavailable("no CUDA-capable GPU detected", notify=explicit)

        if os.name == "nt" and prepare_cuda_libraries() is None:
            raise _CudaUnavailable(cublas_missing_hint(), notify=True)

        try:
            translator = ctranslate2.Translator(
                str(model_dir), device="cuda", compute_type=self._gpu_compute_type,
            )
            # cuBLAS is loaded on the first GPU matmul, not by the constructor,
            # so only a real (tiny) translation shows whether CUDA works.
            translator.translate_batch(
                [["eng_Latn", "▁ok", "</s>"]], target_prefix=[["rus_Cyrl"]],
                beam_size=1, max_decoding_length=4,
            )
        except Exception as exc:
            raise _CudaUnavailable(f"CUDA initialisation failed: {exc}", notify=True) from exc
        return translator

    def unload(self) -> None:
        """Release the model so the next request reloads it (e.g. after a path change)."""
        with self._load_lock:
            self._translator = None
            self._sp = None
            self._model_dir = None
            self._load_seconds = 0.0
            self._active_device = ""
            self._cuda_fallback_reason = ""
            self._pending_notice = ""

    # ── Inference ────────────────────────────────────────

    def _raw_translate(self, text: str, src_code: str, tgt_code: str) -> str:
        """Run one NLLB forward pass. Assumes the model is loaded."""
        pieces = self._sp.encode(text, out_type=str)
        source = [src_code] + pieces + ["</s>"]

        # Diagnostic: which thread calls, which Translator object, how many at once.
        with self._inflight_lock:
            self._inflight += 1
            inflight = self._inflight
        _logger.debug(
            "NLLB inference start | thread=%s | translator=%#x | device=%s | in-flight=%d",
            threading.current_thread().name, id(self._translator), self._active_device, inflight,
        )
        try:
            results = self._translator.translate_batch(
                [source],
                target_prefix=[[tgt_code]],
                beam_size=self._beam_size,
                max_decoding_length=512,
            )
        finally:
            with self._inflight_lock:
                self._inflight -= 1
        _logger.debug("NLLB inference done | thread=%s", threading.current_thread().name)
        hypothesis = results[0].hypotheses[0]
        if hypothesis and hypothesis[0] == tgt_code:
            hypothesis = hypothesis[1:]
        hypothesis = [t for t in hypothesis if t not in ("</s>", "<pad>", "<s>")]
        return self._sp.decode(hypothesis)

    @staticmethod
    def _flores(lang: str) -> str:
        code = NLLB_LANG_CODES.get((lang or "").strip().lower())
        if code is None:
            raise NllbTranslationError(
                f"Язык '{lang}' не поддерживается локальной моделью NLLB. "
                f"Доступны: {', '.join(sorted(SUPPORTED_LANGS))}"
            )
        return code

    @staticmethod
    def _cache_domain(domain_id: str) -> str:
        """Namespace cache keys so local output stays separable from API output."""
        return f"{domain_id}|nllb"

    def _detect_source(self, text: str, target_lang: str) -> str:
        """Offline source-language detection (langid + script heuristic)."""
        from translate.lang_detect import detect_source_lang, get_detector

        try:
            detector = get_detector("langid")
            detected = detect_source_lang(text, detector)
        except Exception:
            detected = None

        if detected and detected.strip().lower() in SUPPORTED_LANGS:
            return detected.strip().lower()

        # Fall back to a sensible non-target language rather than guessing wildly.
        return "en" if target_lang != "en" else "ru"

    # ── Public API (mirrors translate.llm_client) ────────

    def translate(
        self,
        text: str,
        target_lang: str | None = None,
        source_lang: str | None = None,
        domain_id: str | None = None,
        on_chunk=None,
    ) -> str:
        """Translate *text* locally. See ``translate.llm_client.translate``."""
        text = text.strip()
        if not text:
            return ""

        if target_lang is None:
            target_lang = config.TARGET_LANG
        if source_lang is None:
            source_lang = config.SOURCE_LANG
        if domain_id is None:
            domain_id = getattr(config, "ACTIVE_DOMAIN", "general")

        # Same-language fast path — identical semantics to the API backend.
        from translate.lang_detect import is_same_language
        is_same, known = is_same_language(text, target_lang, source_lang=source_lang)
        if is_same:
            _logger.info("NLLB FAST PATH (same language) | src=%s == tgt=%s", known, target_lang)
            if on_chunk is not None:
                on_chunk(text)
            return text

        cache_domain = self._cache_domain(domain_id)
        cached = get_cached(text, source_lang, target_lang, domain_id=cache_domain)
        if cached is not None:
            _logger.info("NLLB CACHE HIT | text=%r", text[:120])
            if on_chunk is not None:
                on_chunk(cached)
            return cached

        self.ensure_loaded()

        resolved_src = source_lang
        if not resolved_src or resolved_src.strip().lower() == "auto":
            resolved_src = self._detect_source(text, target_lang)

        src_code = self._flores(resolved_src)
        tgt_code = self._flores(target_lang)

        t0 = time.perf_counter()
        try:
            translation = self._raw_translate(text, src_code, tgt_code)
        except NllbError:
            raise
        except Exception as exc:
            raise NllbTranslationError(f"Сбой инференса NLLB: {exc}") from exc
        elapsed = time.perf_counter() - t0

        _logger.info(
            "NLLB OK | %s->%s | %.2fs | src=%r | result=%r",
            src_code, tgt_code, elapsed, text[:80], translation[:80],
        )

        save_to_cache(text, source_lang, target_lang, translation, domain_id=cache_domain)
        if on_chunk is not None:
            on_chunk(translation)
        return translation

    def detect_and_translate(
        self,
        text: str,
        target_lang: str | None = None,
        domain_id: str | None = None,
        on_chunk=None,
    ) -> tuple[str, str]:
        """Detect the source language offline, then translate.

        See ``translate.llm_client.detect_and_translate``.
        """
        text = text.strip()
        if not text:
            return config.SOURCE_LANG, ""

        if target_lang is None:
            target_lang = config.TARGET_LANG
        if domain_id is None:
            domain_id = getattr(config, "ACTIVE_DOMAIN", "general")

        from translate.lang_detect import is_same_language
        is_same, known = is_same_language(text, target_lang, source_lang="auto")
        if is_same:
            _logger.info("NLLB FAST PATH (same language, auto) | detected=%s", known)
            if on_chunk is not None:
                on_chunk(text)
            return known or target_lang, text

        cache_domain = self._cache_domain(domain_id)
        cached = get_cached(text, "_auto", target_lang, domain_id=cache_domain)
        if cached is not None:
            _logger.info("NLLB CACHE HIT (auto) | text=%r", text[:120])
            if on_chunk is not None:
                on_chunk(cached)
            return config.SOURCE_LANG, cached

        self.ensure_loaded()

        detected = self._detect_source(text, target_lang)
        src_code = self._flores(detected)
        tgt_code = self._flores(target_lang)

        t0 = time.perf_counter()
        try:
            translation = self._raw_translate(text, src_code, tgt_code)
        except NllbError:
            raise
        except Exception as exc:
            raise NllbTranslationError(f"Сбой инференса NLLB: {exc}") from exc
        elapsed = time.perf_counter() - t0

        _logger.info(
            "NLLB OK (auto) | %s->%s | %.2fs | src=%r | result=%r",
            src_code, tgt_code, elapsed, text[:80], translation[:80],
        )

        save_to_cache(text, "_auto", target_lang, translation, domain_id=cache_domain)
        if on_chunk is not None:
            on_chunk(translation)
        return detected, translation


# ── Module-level singleton (mirrors translate.llm_client) ─

_backend: NllbBackend | None = None
_backend_lock = threading.Lock()


def get_backend() -> NllbBackend:
    """Return the process-wide NllbBackend instance (created on first call)."""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = NllbBackend()
    return _backend


def translate(text: str, target_lang: str | None = None, source_lang: str | None = None,
              domain_id: str | None = None, on_chunk=None) -> str:
    try:
        return get_backend().translate(
            text, target_lang=target_lang, source_lang=source_lang,
            domain_id=domain_id, on_chunk=on_chunk,
        )
    except Exception:
        _logger.exception("NLLB translate() failed | text=%r", text[:120])
        raise


def detect_and_translate(text: str, target_lang: str | None = None,
                         domain_id: str | None = None, on_chunk=None) -> tuple[str, str]:
    try:
        return get_backend().detect_and_translate(
            text, target_lang=target_lang, domain_id=domain_id, on_chunk=on_chunk,
        )
    except Exception:
        _logger.exception("NLLB detect_and_translate() failed | text=%r", text[:120])
        raise


def reset_client() -> None:
    """Drop the loaded model so settings changes (e.g. a new path) take effect."""
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.unload()
        _backend = None
    _logger.info("NLLB backend reset — model will be re-resolved on next request.")


def is_available() -> bool:
    """True if a complete model directory exists (does not load the model)."""
    return resolve_model_dir() is not None
