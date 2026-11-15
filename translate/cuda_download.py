"""
translate/cuda_download.py — download cuBLAS so the local NLLB model can run on an
NVIDIA GPU without a CUDA Toolkit install, and cuDNN, which live subtitles (Whisper)
need on top of it.

The installer ships without CUDA (cuBLAS alone is ~0.5 GB compressed, ~0.8 GB on
disk, and only NVIDIA owners can use it). On request the app fetches the official
``nvidia-cublas-cu12`` wheel from PyPI, checks it against the SHA-256 PyPI
publishes, and unpacks only its DLLs into ``%APPDATA%\\translator-overlay\\cuda``,
where ``translate/cuda_support.py`` finds them. cuDNN (``nvidia-cudnn-cu12``, ~1 GB on
disk) goes the same way into ``...\\cudnn``, where ``audio/stt.py`` finds it.

Only the standard library is used (the frozen app ships without pip). The wheel
version is pinned so every install gets the same, tested build.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

import config

logger = logging.getLogger(__name__)

#: cuBLAS for CUDA 12 (what CTranslate2 4.x is built against). Minor versions are
#: compatible with any CUDA 12 driver.
WHEEL_PACKAGE = "nvidia-cublas-cu12"
WHEEL_VERSION = "12.9.2.10"
#: The wheel's DLLs live here inside the zip.
_WHEEL_BIN = "nvidia/cublas/bin/"
#: cuDNN 9 for CUDA 12: Whisper's convolutional encoder needs it (NLLB does not).
CUDNN_PACKAGE = "nvidia-cudnn-cu12"
CUDNN_VERSION = "9.28.1.4"
_CUDNN_BIN = "nvidia/cudnn/bin/"
#: The library ``audio/stt.py`` looks for.
CUDNN_DLL = "cudnn_ops64_9.dll"
#: A driver older than CUDA 12.0 cannot run CUDA 12 libraries.
MIN_DRIVER_CUDA = 12000

_TIMEOUT_SEC = 20
_CHUNK = 1 << 20


class DownloadCancelled(Exception):
    pass


def cuda_dir() -> Path:
    """Where the downloaded cuBLAS DLLs live (per user, survives app updates)."""
    return Path(config.USER_DATA_DIR) / "cuda"


def cudnn_dir() -> Path:
    """Where the downloaded cuDNN DLLs live (next to ``cuda_dir()``)."""
    return Path(config.USER_DATA_DIR) / "cudnn"


def driver_cuda_version() -> int | None:
    """CUDA version the NVIDIA driver supports (e.g. 12080 for 12.8), None without one.

    Asks ``nvcuda.dll``, which only an NVIDIA driver installs; no GPU work is done.
    """
    if os.name != "nt":
        return None
    try:
        nvcuda = ctypes.WinDLL("nvcuda.dll")
        version = ctypes.c_int(0)
        if nvcuda.cuDriverGetVersion(ctypes.byref(version)) != 0:
            return None
        return version.value or None
    except (OSError, AttributeError):
        return None


def gpu_offer(driver_version: int | None, cublas_found: bool) -> str:
    """What the settings page offers for GPU acceleration.

    ``"none"`` — no NVIDIA driver; ``"old_driver"`` — driver too old for CUDA 12;
    ``"download"`` — offer the cuBLAS download; ``"ready"`` — cuBLAS already there.
    """
    if driver_version is None:
        return "none"
    if cublas_found:
        return "ready"
    if driver_version < MIN_DRIVER_CUDA:
        return "old_driver"
    return "download"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "translator-overlay"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        return json.load(resp)


def wheel_info(package: str = WHEEL_PACKAGE, version: str = WHEEL_VERSION) -> tuple[str, str, int]:
    """``(url, sha256, size)`` of the pinned Windows wheel, from PyPI."""
    data = _get_json(f"https://pypi.org/pypi/{package}/{version}/json")
    for entry in data.get("urls", []):
        if entry.get("filename", "").endswith("win_amd64.whl"):
            return entry["url"], entry["digests"]["sha256"], int(entry.get("size", 0))
    raise OSError(f"{package} {version} has no Windows wheel on PyPI")


def extract_dlls(wheel: Path, dest: Path, prefix: str = _WHEEL_BIN) -> list[str]:
    """Unpack the ``.dll`` files under *prefix* (``nvidia/cublas/bin/``) of *wheel* into *dest*."""
    names = []
    with zipfile.ZipFile(wheel) as zf:
        for member in zf.namelist():
            if not (member.startswith(prefix) and member.lower().endswith(".dll")):
                continue
            name = Path(member).name  # flat: never trust paths inside the archive
            with zf.open(member) as src, open(dest / name, "wb") as out:
                shutil.copyfileobj(src, out, _CHUNK)
            names.append(name)
    return names


def download_cublas(
    *,
    dest: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download and unpack cuBLAS into *dest* (default ``cuda_dir()``); return it.

    The wheel goes to a temp file and the DLLs to ``<dest>.part``; *dest* is
    replaced only after the checksum matches and the DLLs are unpacked, so a
    failed or cancelled download never leaves a half-written directory that
    ``cuda_support`` would pick up. ``progress(done_bytes, total_bytes)`` is
    called from the calling thread.
    """
    from translate.cuda_support import CUBLAS_DLL

    return _download_wheel_dlls(
        WHEEL_PACKAGE, WHEEL_VERSION, _WHEEL_BIN, CUBLAS_DLL, "cuBLAS", dest or cuda_dir(), progress, cancel
    )


def download_cudnn(
    *,
    dest: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download and unpack cuDNN into *dest* (default ``cudnn_dir()``); see ``download_cublas``."""
    return _download_wheel_dlls(
        CUDNN_PACKAGE, CUDNN_VERSION, _CUDNN_BIN, CUDNN_DLL, "cuDNN", dest or cudnn_dir(), progress, cancel
    )


def _download_wheel_dlls(
    package: str,
    version: str,
    prefix: str,
    required_dll: str,
    label: str,
    dest: Path,
    progress: Callable[[int, int], None] | None,
    cancel: threading.Event | None,
) -> Path:
    part = dest.with_name(dest.name + ".part")
    wheel = dest.with_name(dest.name + ".whl.part")
    url, expected_sha256, total = wheel_info(package, version)

    shutil.rmtree(part, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        digest = hashlib.sha256()
        done = 0
        req = urllib.request.Request(url, headers={"User-Agent": "translator-overlay"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp, open(wheel, "wb") as out:
            total = total or int(resp.headers.get("Content-Length") or 0)
            while chunk := resp.read(_CHUNK):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if digest.hexdigest() != expected_sha256:
            raise OSError(f"Checksum mismatch for the {label} wheel")

        part.mkdir()
        names = extract_dlls(wheel, part, prefix)
        if required_dll not in names:
            raise OSError(f"{required_dll} is missing from the {label} wheel")
        (part / "version.json").write_text(
            json.dumps({"package": package, "version": version}, indent=2),
            encoding="utf-8",
        )
        shutil.rmtree(dest, ignore_errors=True)
        try:
            part.rename(dest)
        except OSError:
            # The old copy could not be removed: its DLLs are loaded by a running model
            # (or another download just finished). A working copy is there, so keep it.
            if not (dest / required_dll).is_file():
                raise
            shutil.rmtree(part, ignore_errors=True)
            logger.info("%s in %s is in use, keeping the existing copy", label, dest)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    finally:
        wheel.unlink(missing_ok=True)

    logger.info("Downloaded %s %s into %s", label, version, dest)
    return dest
