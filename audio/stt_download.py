"""
audio/stt_download.py — download a Whisper model for live subtitles.

Like the NLLB model, the speech model is fetched only by an explicit user action (the
button in Settings → Subtitles); ``audio/stt.py`` itself never touches the network.
The CTranslate2 conversions published by Systran on the Hugging Face Hub are used. Files
go to ``%APPDATA%\\translator-overlay\\models\\whisper-<name>`` (the second place
``stt.model_dirs()`` looks in) through a ``.part`` directory, so an interrupted download
is never picked up as a model; the next attempt for the same commit resumes it.

Only the standard library is used (shared helpers of ``translate/nllb_models.py``).
"""

from __future__ import annotations

import logging
import shutil
import threading
import urllib.error
import urllib.parse
from collections.abc import Callable
from pathlib import Path

import config
from audio import stt
from translate import nllb_models
from translate.nllb_models import DownloadCancelled

_logger = logging.getLogger("translator.stt")

#: Model name (``config.SUBTITLES_MODEL``) → repository with its CTranslate2 conversion.
REPOS = {
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base.en": "Systran/faster-whisper-base.en",
    "small.en": "Systran/faster-whisper-small.en",
    "small": "Systran/faster-whisper-small",  # multilingual: needed by the language filter
}
REVISION = "main"
#: Download sizes shown before the download starts.
APPROX_MB = {"tiny.en": 75, "base.en": 140, "small.en": 465, "small": 465}
#: Files faster-whisper reads; the rest of a repository (README, …) is skipped.
_WANTED_FILES = (
    "model.bin",
    "config.json",
    "tokenizer.json",
    "preprocessor_config.json",
    "vocabulary.txt",
    "vocabulary.json",
)

__all__ = ["APPROX_MB", "REPOS", "DownloadCancelled", "download_dir", "download_model", "is_downloadable"]


def is_downloadable(name: str) -> bool:
    return name in REPOS


def download_dir(name: str) -> Path:
    """Where ``download_model`` puts *name* (per user, survives app updates)."""
    return Path(config.USER_DATA_DIR) / "models" / stt.model_dirname(name)


def download_model(
    name: str,
    *,
    dest: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download Whisper model *name* into *dest* (default ``download_dir(name)``); return it.

    ``progress(done_bytes, total_bytes)`` is called from the calling thread. Raises
    ``DownloadCancelled``, ``KeyError`` for an unknown model and ``OSError`` otherwise.
    """
    repo_id = REPOS[name]
    dest = dest or download_dir(name)
    part = dest.with_name(dest.name + ".part")

    sha = nllb_models.resolve_revision(REVISION, repo_id)
    files = [f for f in nllb_models._repo_files(repo_id, sha) if f.get("path") in _WANTED_FILES]
    total = sum(int(f.get("size", 0)) for f in files)
    done = 0

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        if progress is not None:
            progress(done, total)

    marker = part / nllb_models.PART_MARKER
    try:
        same_commit = marker.is_file() and marker.read_text() == sha
    except OSError:
        same_commit = False
    if not same_commit:
        shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True, exist_ok=True)
    marker.write_text(sha, encoding="utf-8")
    try:
        for entry in files:
            rel = entry["path"]  # a bare file name: checked against _WANTED_FILES above
            nllb_models._fetch_file(
                f"{nllb_models.HF_ENDPOINT}/{repo_id}/resolve/{sha}/{urllib.parse.quote(rel)}",
                part / rel,
                size=int(entry.get("size", 0)),
                expected_sha256=(entry.get("lfs") or {}).get("oid"),
                on_bytes=on_bytes,
                cancel=cancel,
            )
        marker.unlink(missing_ok=True)
        missing = stt.missing_files(part)
        if missing:
            raise OSError(f"Whisper model {name} lacks required files: {', '.join(missing)}")
        # dest is the app's own download folder; whatever is there is an incomplete model.
        shutil.rmtree(dest, ignore_errors=True)
        part.rename(dest)
    except (DownloadCancelled, urllib.error.URLError, TimeoutError, ConnectionError):
        raise  # keep the .part directory: the next attempt resumes it
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise

    _logger.info("Downloaded Whisper model %s (%s) into %s", name, sha[:12], dest)
    return dest
