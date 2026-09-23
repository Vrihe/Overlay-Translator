"""
translate/cuda_support.py — locate the CUDA libraries CTranslate2 needs for GPU inference.

GPU inference is an optional speed-up for the local NLLB backend. CTranslate2's
Windows wheels ship without CUDA; the only extra library NLLB actually needs is
cuBLAS (``cublas64_12.dll`` + ``cublasLt64_12.dll``, CUDA 12.x). It can come from:

  1. The ``nvidia-cublas-cu12`` pip wheel      → <site-packages>/nvidia/cublas/bin
  2. A CUDA Toolkit install pointed to by env  → %CUDA_PATH%\\bin, %CUDA_PATH_V12_*%\\bin
  3. A CUDA Toolkit in its default location    → C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.*\\bin

CTranslate2 resolves cuBLAS with a plain ``LoadLibrary`` call, which searches
``PATH`` but ignores ``os.add_dll_directory``. The directory is therefore
prepended to ``PATH`` (and registered with ``add_dll_directory`` as well, for
any dependent DLLs loaded with the safe search flags).

cuBLAS is loaded lazily on the first GPU matrix multiply, not when the
``Translator`` is created, so callers must run a warm-up translation to find out
whether CUDA actually works.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_logger = logging.getLogger("translator.cuda")

#: The DLL whose presence marks a usable directory (CTranslate2 4.x is built for CUDA 12).
CUBLAS_DLL = "cublas64_12.dll"

_DEFAULT_TOOLKIT_ROOT = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")

# Directories already registered in this process, so repeated loads stay idempotent.
_registered: set[str] = set()


def _pip_wheel_dirs() -> list[Path]:
    """``nvidia/cublas/bin`` under every import root (venv, user site, frozen bundle)."""
    roots = list(sys.path)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        roots.insert(0, frozen_root)
    return [Path(root) / "nvidia" / "cublas" / "bin" for root in roots if root]


def _toolkit_env_dirs() -> list[Path]:
    """``bin`` of every toolkit named by CUDA_PATH / CUDA_PATH_V12_x, newest version first."""
    versioned = sorted(
        (key for key in os.environ if key.upper().startswith("CUDA_PATH_V12")),
        reverse=True,
    )
    dirs = []
    for key in ["CUDA_PATH", *versioned]:
        value = (os.environ.get(key) or "").strip()
        if value:
            dirs.append(Path(value) / "bin")
    return dirs


def _toolkit_default_dirs() -> list[Path]:
    """``bin`` of CUDA 12.x toolkits in the default install location, newest first."""
    if not _DEFAULT_TOOLKIT_ROOT.is_dir():
        return []
    return [path / "bin" for path in sorted(_DEFAULT_TOOLKIT_ROOT.glob("v12.*"), reverse=True)]


def candidate_dirs() -> list[Path]:
    """Every directory that may hold cuBLAS, in priority order, without duplicates."""
    seen: set[str] = set()
    unique: list[Path] = []
    for path in [*_pip_wheel_dirs(), *_toolkit_env_dirs(), *_toolkit_default_dirs()]:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_cublas_dir() -> Path | None:
    """Return the first candidate directory that contains ``cublas64_12.dll``."""
    for path in candidate_dirs():
        if (path / CUBLAS_DLL).is_file():
            return path
    return None


def prepare_cuda_libraries() -> Path | None:
    """Make cuBLAS loadable for CTranslate2. Returns the directory used, or None.

    Only Windows needs this: on Linux the libraries must already be on the
    loader path, since ``LD_LIBRARY_PATH`` cannot be changed after start-up.
    """
    if os.name != "nt":
        return None

    found = find_cublas_dir()
    if found is None:
        return None

    key = os.path.normcase(str(found))
    if key not in _registered:
        os.environ["PATH"] = str(found) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(found))
            except OSError as exc:
                _logger.debug("add_dll_directory(%s) failed: %s", found, exc)
        _registered.add(key)
        _logger.info("CUDA libraries: using cuBLAS from %s", found)
    return found


def cublas_missing_hint() -> str:
    """Explain where cuBLAS was searched for and how to install it."""
    searched = "\n".join(f"  • {path}" for path in candidate_dirs())
    return (
        f"{CUBLAS_DLL} not found (pip install nvidia-cublas-cu12, or install CUDA Toolkit 12.x)"
        "\nSearched:\n" + (searched or "  (no candidate directories)")
    )
