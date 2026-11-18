"""
audio/packages.py — the Python packages live subtitles need, and their installation.

    missing_packages()      # ["faster-whisper", "PyAudioWPatch"] — what cannot be imported
    can_install()           # True when running from source with requirements-voice.txt at hand
    install(cancel=event)   # pip install --no-deps -r requirements-voice.txt; raises PackagesInstallError

Nothing is imported here (``importlib.util.find_spec`` only looks), and nothing is installed
except by an explicit call: the Subtitles tab calls ``install()`` from a button.

``--no-deps`` is required, not a detail: faster-whisper declares the plain ``onnxruntime``
wheel, which would overwrite ``onnxruntime-directml`` (the OCR engine). See
``requirements-voice.txt``. A packaged build (PyInstaller) already contains them, so it cannot
and need not install anything.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import config

_logger = logging.getLogger("translator.subtitles")

#: (import name, name shown to the user) of every package live subtitles import.
REQUIRED = (
    ("faster_whisper", "faster-whisper"),
    ("av", "av"),
    ("tokenizers", "tokenizers"),
    ("pyaudiowpatch", "PyAudioWPatch"),
)

_CREATE_NO_WINDOW = 0x08000000


class PackagesInstallError(Exception):
    """pip failed or could not be started; the message is the reason."""


class InstallCancelled(Exception):
    pass


def missing_packages() -> list[str]:
    """Display names of the required packages that are not installed."""
    importlib.invalidate_caches()
    return [shown for module, shown in REQUIRED if importlib.util.find_spec(module) is None]


def requirements_file() -> Path:
    return Path(config._PROJECT_DIR) / "requirements-voice.txt"


def can_install() -> bool:
    """Installing is possible from source only: a packaged build has no pip to run."""
    return not getattr(sys, "frozen", False) and requirements_file().is_file()


def _python() -> str:
    """The interpreter that runs the app, console version (pip must not open a window)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console) if exe.name.lower() == "pythonw.exe" and console.is_file() else str(exe)


def install(*, cancel: threading.Event | None = None) -> None:
    """Install requirements-voice.txt into the running interpreter's environment."""
    if not can_install():
        raise PackagesInstallError("requirements-voice.txt not found or the app is packaged")
    command = [_python(), "-m", "pip", "install", "--no-deps", "-r", str(requirements_file())]
    _logger.info("Installing live-subtitle packages: %s", " ".join(command[1:]))
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise PackagesInstallError(str(exc)) from exc

    tail: list[str] = []

    def read() -> None:
        for line in process.stdout:
            tail.append(line.rstrip())
            del tail[:-8]

    reader = threading.Thread(target=read, name="pip-output", daemon=True)
    reader.start()
    stop = cancel or threading.Event()
    while process.poll() is None:
        if stop.wait(0.2):
            process.terminate()
            process.wait(10)
            raise InstallCancelled()
    reader.join(2.0)
    if process.returncode != 0:
        reason = next((line for line in reversed(tail) if line.strip()), f"pip exit code {process.returncode}")
        raise PackagesInstallError(reason)
    importlib.invalidate_caches()
    left = missing_packages()
    if left:
        raise PackagesInstallError(f"still missing after install: {', '.join(left)}")
