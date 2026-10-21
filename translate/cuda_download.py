"""
translate/cuda_download.py — download cuBLAS so the local NLLB model can run on an
NVIDIA GPU without a CUDA Toolkit install.

The installer ships without CUDA (cuBLAS alone is ~0.5 GB compressed, ~0.8 GB on
disk, and only NVIDIA owners can use it). On request the app fetches the official
``nvidia-cublas-cu12`` wheel from PyPI, checks it against the SHA-256 PyPI
publishes, and unpacks only its DLLs into ``%APPDATA%\\translator-overlay\\cuda``,
where ``translate/cuda_support.py`` finds them.

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
#: A driver older than CUDA 12.0 cannot run CUDA 12 libraries.
MIN_DRIVER_CUDA = 12000

_TIMEOUT_SEC = 20
_CHUNK = 1 << 20


class DownloadCancelled(Exception):
    pass


def cuda_dir() -> Path:
    """Where the downloaded cuBLAS DLLs live (per user, survives app updates)."""
    return Path(config.USER_DATA_DIR) / "cuda"


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


def wheel_info() -> tuple[str, str, int]:
    """``(url, sha256, size)`` of the pinned Windows wheel, from PyPI."""
    data = _get_json(f"https://pypi.org/pypi/{WHEEL_PACKAGE}/{WHEEL_VERSION}/json")
    for entry in data.get("urls", []):
        if entry.get("filename", "").endswith("win_amd64.whl"):
            return entry["url"], entry["digests"]["sha256"], int(entry.get("size", 0))
    raise OSError(f"{WHEEL_PACKAGE} {WHEEL_VERSION} has no Windows wheel on PyPI")


def extract_dlls(wheel: Path, dest: Path) -> list[str]:
    """Unpack the ``.dll`` files under ``nvidia/cublas/bin/`` of *wheel* into *dest*."""
    names = []
    with zipfile.ZipFile(wheel) as zf:
        for member in zf.namelist():
            if not (member.startswith(_WHEEL_BIN) and member.lower().endswith(".dll")):
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

    dest = dest or cuda_dir()
    part = dest.with_name(dest.name + ".part")
    wheel = dest.with_name(dest.name + ".whl.part")
    url, expected_sha256, total = wheel_info()

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
            raise OSError("Checksum mismatch for the cuBLAS wheel")

        part.mkdir()
        names = extract_dlls(wheel, part)
        if CUBLAS_DLL not in names:
            raise OSError(f"{CUBLAS_DLL} is missing from the cuBLAS wheel")
        (part / "version.json").write_text(
            json.dumps({"package": WHEEL_PACKAGE, "version": WHEEL_VERSION}, indent=2),
            encoding="utf-8",
        )
        shutil.rmtree(dest, ignore_errors=True)
        part.rename(dest)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    finally:
        wheel.unlink(missing_ok=True)

    logger.info("Downloaded cuBLAS %s into %s", WHEEL_VERSION, dest)
    return dest
