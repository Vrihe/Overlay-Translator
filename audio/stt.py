"""
audio/stt.py — speech-to-text for live subtitles: Whisper on CTranslate2 (faster-whisper).

    recognizer = SpeechRecognizer()          # nothing is loaded yet
    recognizer.ensure_loaded()               # raises SttModelUnavailable
    text = recognizer.transcribe(phrase.audio)

Rules, the same as for the local NLLB model:
  • The model is never downloaded implicitly: it must already be on disk (see
    ``model_dirs()``); ``local_files_only=True`` keeps faster-whisper off the network.
  • ``faster_whisper`` is imported lazily, inside ``ensure_loaded()``.
  • ``device="auto"`` uses an NVIDIA GPU when cuBLAS **and cuDNN 9** are found, and
    the CPU otherwise. Any CUDA failure falls back to the CPU with a one-shot notice.

Speech language (``language``): a code such as "en" or "ru", or "auto" — Whisper then
detects the language of every phrase (``last_language`` tells which one it was). Only
multilingual models can do that; an English-only model always recognises English.

Language filter (``skip_foreign=True``, mixed-language voice chats): a multilingual
model (``small``, not ``small.en``) first detects the language of each phrase; a phrase
confidently detected as another language is skipped — ``transcribe()`` returns "" for it —
instead of being decoded as if it were English. English-only models cannot detect the
language, so the filter is off for them.

Decoding parameters are fixed to the values measured in the prototype
(docs/VOICE_TRANSLATION_PROTOTYPE.md): beam 1, a fixed language (no detection pass),
no conditioning on previous text, no timestamps.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import config
from i18n import tr
from translate.privacy import loggable

_logger = logging.getLogger("translator.stt")

#: Default model: the best accuracy that still runs in real time on a mid-range GPU.
DEFAULT_MODEL = "small.en"
#: Accepted values for the ``device`` argument.
DEVICES = ("auto", "cuda", "cpu")

#: A phrase is skipped by the language filter only when another language is detected
#: with at least this probability; short or unclear phrases are let through.
FOREIGN_MIN_PROBABILITY = 0.5

_REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json")
#: Whisper's convolutional encoder needs cuDNN on the GPU (NLLB does not).
CUDNN_DLL = "cudnn_ops64_9.dll"

_cudnn_registered: set[str] = set()


class SttModelUnavailable(Exception):
    """The speech model cannot be used: not on disk, incomplete, or packages missing."""


class _CudaUnavailable(Exception):
    def __init__(self, message: str, notify: bool) -> None:
        super().__init__(message)
        self.notify = notify


# ── Model discovery ──────────────────────────────────────


def is_multilingual(name: str) -> bool:
    """Whether Whisper model *name* can detect the language (``small``, not ``small.en``)."""
    return not name.endswith(".en")


def model_dirname(name: str) -> str:
    return f"whisper-{name}"


def model_dirs(name: str = DEFAULT_MODEL) -> list[Path]:
    """Where a Whisper model is looked for, in order: the project, then user data."""
    return [
        Path(config._PROJECT_DIR) / "models" / model_dirname(name),
        Path(config.USER_DATA_DIR) / "models" / model_dirname(name),
    ]


def missing_files(path: Path) -> list[str]:
    return [name for name in _REQUIRED_FILES if not (path / name).is_file()]


def resolve_model_dir(name: str = DEFAULT_MODEL) -> Path | None:
    """Return the first complete model directory, or None."""
    for path in model_dirs(name):
        if not missing_files(path):
            return path
    return None


# ── cuDNN discovery ──────────────────────────────────────


def cudnn_candidate_dirs() -> list[Path]:
    """Directories that may hold cuDNN 9: the app's download folders, the pip wheel, toolkits."""
    from translate import cuda_support
    from translate.cuda_download import cuda_dir, cudnn_dir

    roots = list(sys.path)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        roots.insert(0, frozen_root)
    wheel_dirs = [Path(root) / "nvidia" / "cudnn" / "bin" for root in roots if root]
    return [
        cudnn_dir(),
        cuda_dir(),
        *wheel_dirs,
        *cuda_support._toolkit_env_dirs(),
        *cuda_support._toolkit_default_dirs(),
    ]


def find_cudnn_dir() -> Path | None:
    for path in cudnn_candidate_dirs():
        if (path / CUDNN_DLL).is_file():
            return path
    return None


def prepare_cudnn() -> Path | None:
    """Put cuDNN on PATH (CTranslate2 loads it with plain LoadLibrary). Windows only."""
    if os.name != "nt":
        return None
    found = find_cudnn_dir()
    if found is None:
        return None
    key = os.path.normcase(str(found))
    if key not in _cudnn_registered:
        os.environ["PATH"] = str(found) + os.pathsep + os.environ.get("PATH", "")
        _cudnn_registered.add(key)
        _logger.info("CUDA libraries: using cuDNN from %s", found)
    return found


# ── Recognizer ───────────────────────────────────────────


class SpeechRecognizer:
    """Lazily-loaded Whisper model. ``transcribe()`` may be called from one thread at a time."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        model_dir: str | Path | None = None,
        device: str = "auto",
        language: str = "en",
        beam_size: int = 1,
        cpu_threads: int | None = None,
        skip_foreign: bool = False,
    ) -> None:
        self._model_name = model_name
        wanted = (language or "auto").strip().lower()
        multilingual = is_multilingual(model_name)
        if not multilingual and wanted != "en":
            _logger.info("Model %s is English-only: speech language %r is ignored", model_name, wanted)
            wanted = "en"
        #: None = detect the language of every phrase.
        self._language = None if wanted == "auto" else wanted
        #: Language of the phrase recognised last ("" before the first one).
        self.last_language = ""
        # Nothing is "foreign" when every language is accepted.
        self._skip_foreign = bool(skip_foreign) and multilingual and self._language is not None
        if skip_foreign and not self._skip_foreign:
            _logger.info("Language filter is off (model %s, language %s)", model_name, wanted)
        self.skipped_foreign = 0
        self._explicit_dir = Path(model_dir) if model_dir else None
        requested = (device or "auto").strip().lower()
        if requested not in DEVICES:
            _logger.warning("Unknown STT device %r, using 'auto'", requested)
            requested = "auto"
        self._device = requested
        self._beam_size = beam_size
        self._cpu_threads = cpu_threads or min(4, os.cpu_count() or 4)

        self._model = None
        self._model_dir: Path | None = None
        self._active_device = ""
        self._load_seconds = 0.0
        self._pending_notice = ""
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def filters_language(self) -> bool:
        """Whether phrases in other languages are skipped (needs a multilingual model)."""
        return self._skip_foreign

    @property
    def active_device(self) -> str:
        """Device the loaded model runs on ("cuda" or "cpu"); "" when not loaded."""
        return self._active_device

    @property
    def model_dir(self) -> Path | None:
        return self._model_dir

    @property
    def load_seconds(self) -> float:
        return self._load_seconds

    def take_notice(self) -> str:
        """Return and clear the one-shot user notice left by the last load."""
        notice, self._pending_notice = self._pending_notice, ""
        return notice

    # ── Loading ──────────────────────────────────────────

    def ensure_loaded(self) -> None:
        """Load the model if needed. Raises ``SttModelUnavailable``."""
        if self.is_loaded:
            return
        with self._load_lock:
            if self.is_loaded:
                return

            model_dir = self._explicit_dir or resolve_model_dir(self._model_name)
            if model_dir is None:
                searched = "\n".join(f"  • {p}" for p in model_dirs(self._model_name))
                raise SttModelUnavailable(
                    tr("Модель распознавания речи {name} не найдена. Искали в:\n", name=self._model_name) + searched
                )
            if missing_files(model_dir):
                raise SttModelUnavailable(
                    tr(
                        "Каталог модели {path} неполон — отсутствуют файлы: {files}",
                        path=model_dir,
                        files=", ".join(missing_files(model_dir)),
                    )
                )
            try:
                import faster_whisper
            except ImportError as exc:
                raise SttModelUnavailable(tr("Не установлен пакет faster-whisper для распознавания речи.")) from exc

            t0 = time.perf_counter()
            model, device = self._create_model(faster_whisper, model_dir)
            self._model = model
            self._model_dir = model_dir
            self._active_device = device
            self._load_seconds = time.perf_counter() - t0
            _logger.info("Whisper loaded from %s in %.2fs (device=%s)", model_dir, self._load_seconds, device)

    def _create_model(self, faster_whisper, model_dir: Path):
        if self._device in ("auto", "cuda"):
            try:
                return self._create_cuda_model(faster_whisper, model_dir), "cuda"
            except _CudaUnavailable as exc:
                if exc.notify:
                    _logger.warning("CUDA unavailable, running speech recognition on CPU: %s", exc)
                    first_line = str(exc).splitlines()[0]
                    self._pending_notice = tr(
                        "CUDA недоступна, распознавание речи на CPU ({reason})", reason=first_line
                    )
                else:
                    _logger.info("CUDA not used, running speech recognition on CPU: %s", exc)
        try:
            model = faster_whisper.WhisperModel(
                str(model_dir),
                device="cpu",
                compute_type="int8",
                cpu_threads=self._cpu_threads,
                local_files_only=True,
            )
        except Exception as exc:
            raise SttModelUnavailable(
                tr("Не удалось загрузить модель распознавания речи из {path}: {error}", path=model_dir, error=exc)
            ) from exc
        return model, "cpu"

    def _create_cuda_model(self, faster_whisper, model_dir: Path):
        """Create a GPU model and prove it works, or raise ``_CudaUnavailable``."""
        import ctranslate2

        from translate.cuda_support import prepare_cuda_libraries

        explicit = self._device == "cuda"
        try:
            gpu_count = ctranslate2.get_cuda_device_count()
        except Exception as exc:
            raise _CudaUnavailable(f"CUDA query failed: {exc}", notify=explicit) from exc
        if gpu_count == 0:
            raise _CudaUnavailable("no CUDA-capable GPU detected", notify=explicit)

        if os.name == "nt":
            # Checked before the model is created: with cuDNN missing, CTranslate2 does
            # not raise on the first convolution, it aborts the whole process.
            if prepare_cuda_libraries() is None:
                raise _CudaUnavailable("cuBLAS not found", notify=explicit)
            if prepare_cudnn() is None:
                raise _CudaUnavailable(f"{CUDNN_DLL} not found", notify=explicit)

        try:
            model = faster_whisper.WhisperModel(
                str(model_dir), device="cuda", compute_type="float16", local_files_only=True
            )
            self._run(model, _silence(0.5))  # CUDA libraries load on first use
        except Exception as exc:
            raise _CudaUnavailable(f"CUDA initialisation failed: {exc}", notify=True) from exc
        return model

    def unload(self) -> None:
        with self._load_lock:
            self._model = None
            self._model_dir = None
            self._active_device = ""
            self._load_seconds = 0.0
            self._pending_notice = ""

    # ── Inference ────────────────────────────────────────

    def transcribe(self, audio) -> str:
        """Return the text of one phrase (16 kHz mono float32); "" for no speech."""
        self.ensure_loaded()
        t0 = time.perf_counter()
        if self._skip_foreign and self._is_foreign(audio):
            return ""
        text = self._run(self._model, audio)
        _logger.info(
            "STT | %.2fs audio in %.2fs | text=%s", len(audio) / 16000, time.perf_counter() - t0, loggable(text)
        )
        return text

    def _is_foreign(self, audio) -> bool:
        """True when the phrase is confidently in a language other than ours."""
        try:
            language, probability, _all = self._model.detect_language(audio)
        except Exception:
            _logger.exception("Language detection failed, phrase kept")
            return False
        if language == self._language or probability < FOREIGN_MIN_PROBABILITY:
            return False
        self.skipped_foreign += 1
        _logger.info("STT | phrase skipped: language %s (p=%.2f)", language, probability)
        return True

    def _run(self, model, audio) -> str:
        segments, info = model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        self.last_language = self._language or getattr(info, "language", "") or ""
        return text


def _silence(seconds: float):
    import numpy as np

    return np.zeros(int(16000 * seconds), dtype="float32")
