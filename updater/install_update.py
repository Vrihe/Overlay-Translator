"""
updater/install_update.py — one-click update: download the new installer from the
latest GitHub release, check it, and let it replace the app without any windows.

Flow (``MainWindow`` update banner → "Обновить"):
  1. ``latest_release()`` — tag, page, ``Setup.exe`` URL and its SHA-256 (GitHub's
     asset ``digest``, else the checksum line of the release notes).
  2. ``download_setup()`` — into ``%TEMP%``, verified before it is kept.
  3. ``launch_installer()`` — a hidden PowerShell waits until this process has
     exited, then runs the setup ``/VERYSILENT``. Inno Setup refuses to run while
     the app's mutex exists and a silent setup answers that prompt with Cancel, so
     the setup must not start before the app is gone.
  4. The app quits; the setup's ``/RELAUNCH=1`` entry starts the new version.

Only an Inno Setup install can update itself (``can_self_update()``); a source
run or a copied ``dist`` folder gets the release page instead.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import config
from updater.check_update import _parse_version

_logger = logging.getLogger("translator")

_TIMEOUT_SEC = 20
_CHUNK = 1 << 20
_SETUP_NAME = re.compile(r"^TranslatorOverlay-Setup-[\w.\-]+\.exe$")
_NOTES_SHA256 = re.compile(r"SHA-256[^`]*`[^`]*`:\s*`([0-9A-Fa-f]{64})`")
#: Silent install; /RELAUNCH=1 makes the setup start the app again (installer/*.iss).
INSTALLER_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1")


class DownloadCancelled(Exception):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    html_url: str
    setup_url: str
    setup_name: str
    sha256: str
    size: int


def release_from_json(data: dict) -> Release | None:
    """The installer of a GitHub release (API JSON); None when it has no usable one."""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if not _SETUP_NAME.match(name):
            continue
        digest = (asset.get("digest") or "").lower()
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        if not sha256:
            match = _NOTES_SHA256.search(data.get("body") or "")
            sha256 = match.group(1).lower() if match else ""
        if not sha256:
            return None  # never install a file that cannot be checked
        return Release(
            tag=data.get("tag_name", ""),
            html_url=data.get("html_url", ""),
            setup_url=asset.get("browser_download_url", ""),
            setup_name=name,
            sha256=sha256,
            size=int(asset.get("size") or 0),
        )
    return None


def latest_release(repo: str | None = None) -> Release | None:
    """The latest release if it is newer than this app and has a checkable installer."""
    repo = repo or getattr(config, "GITHUB_REPO", "Vrihe/Overlay-Translator")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": "OverlayTranslator-App", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        data = json.load(resp)
    if _parse_version(data.get("tag_name", "")) <= _parse_version(getattr(config, "APP_VERSION", "0")):
        return None
    return release_from_json(data)


def can_self_update() -> bool:
    """True for an app installed by its setup (the uninstaller sits next to the exe)."""
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return False
    return (Path(sys.executable).resolve().parent / "unins000.exe").is_file()


def download_setup(
    release: Release,
    *,
    dest_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download the release's installer and return its path, checked against SHA-256.

    The file is written as ``<name>.part`` and renamed only after the checksum
    matches, so a failed or cancelled download never leaves a runnable setup.
    """
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "translator-overlay-update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / release.setup_name
    part = final.with_name(final.name + ".part")
    try:
        digest = hashlib.sha256()
        done, total = 0, release.size
        req = urllib.request.Request(release.setup_url, headers={"User-Agent": "OverlayTranslator-App"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp, open(part, "wb") as out:
            total = total or int(resp.headers.get("Content-Length") or 0)
            while chunk := resp.read(_CHUNK):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if digest.hexdigest() != release.sha256:
            raise OSError("Checksum mismatch for the downloaded installer")
        final.unlink(missing_ok=True)
        part.rename(final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    _logger.info("Downloaded update %s (%s)", release.tag, final)
    return final


def waiter_script(setup: Path, pid: int) -> str:
    """PowerShell that waits for *pid* to exit, then runs *setup* silently."""
    quoted = str(setup).replace("'", "''")
    args = ",".join(f"'{a}'" for a in INSTALLER_ARGS)
    return (
        f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath '{quoted}' -ArgumentList {args}"
    )


def launch_installer(setup: Path, *, pid: int | None = None) -> None:
    """Start the hidden waiter; the caller quits right after. Raises if it cannot start."""
    script = waiter_script(setup, pid or os.getpid())
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # CREATE_NO_WINDOW, not DETACHED_PROCESS: PowerShell without any console exits
    # at once without running the script (measured); a hidden console works.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        creationflags=flags,
        close_fds=True,
    )
    _logger.info("Update installer scheduled after exit: %s", setup)
