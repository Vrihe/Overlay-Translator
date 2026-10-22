"""
updater/install_update.py — one-click update: download the new version from the
latest GitHub release, check it, and let it replace the app without any windows.

Flow (``MainWindow`` update banner → "Обновить" → ``prepare_update`` → ``launch_update``):
  1. ``latest_release()`` — tag, page, ``Setup.exe`` URL and its SHA-256 (GitHub's
     asset ``digest``, else the checksum line of the release notes); also the app
     zip and ``update-manifest.json`` when the release has them.
  2. ``choose_update_path()`` — "app" when the installed deps layer is exactly the
     new release's (same ``deps_fingerprint`` and ``runtime`` in the installed and
     the new manifest), else "full".
  3. App path: ``download_app_zip()`` (~14 MB) → ``launch_app_update()``: a hidden
     PowerShell waits until this process has exited, swaps the app-layer files
     (old ones kept as ``*.old`` until the end, restored on any error), updates the
     "Apps & features" version and starts the app again.
     A version whose app-only update failed (download, swap or its start) is
     marked in the user data dir and takes the full path from then on.
     Full path, or any failure of the app path while downloading:
     ``download_setup()`` → ``launch_installer()``: the waiter runs the setup
     ``/VERYSILENT``. Inno Setup refuses to run while the app's mutex exists and a
     silent setup answers that prompt with Cancel, so it must not start before the
     app is gone; its ``/RELAUNCH=1`` entry starts the new version.
  4. The app quits.

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
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import config
from updater.check_update import _parse_version

_logger = logging.getLogger("translator")

_TIMEOUT_SEC = 20
_CHUNK = 1 << 20
_MANIFEST_MAX_BYTES = 1 << 20
_SETUP_NAME = re.compile(r"^TranslatorOverlay-Setup-[\w.\-]+\.exe$")
_APP_ZIP_NAME = re.compile(r"^TranslatorOverlay-app-[\w.\-]+\.zip$")
MANIFEST_NAME = "update-manifest.json"  # build.py UPDATE_MANIFEST; installed into {app}
APP_EXE = "TranslatorOverlay.exe"
#: installer/TranslatorOverlay.iss AppId: the "Apps & features" entry of the install.
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{0DF3004C-2D3C-431A-8BCA-DC181526B77D}_is1"
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
    # App-only update assets (build.py --update-package); empty for older releases.
    manifest_url: str = ""
    manifest_sha256: str = ""
    app_url: str = ""
    app_name: str = ""
    app_sha256: str = ""
    app_size: int = 0


@dataclass(frozen=True)
class PreparedUpdate:
    """A downloaded, verified update: the app zip (with its manifest) or Setup.exe."""

    release: Release
    path: Path
    manifest: dict | None = None  # set for an app-only update

    @property
    def app_only(self) -> bool:
        return self.manifest is not None


def _asset_sha256(asset: dict, body: str) -> str:
    """SHA-256 of a release asset: GitHub's ``digest``, else its line in the notes."""
    digest = (asset.get("digest") or "").lower()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    name = re.escape(asset.get("name", ""))
    match = re.search(rf"SHA-256[^`\n]*`{name}`:\s*`([0-9A-Fa-f]{{64}})`", body)
    return match.group(1).lower() if match else ""


def release_from_json(data: dict) -> Release | None:
    """The installer of a GitHub release (API JSON); None when it has no usable one."""
    body = data.get("body") or ""
    assets = data.get("assets", [])
    setup = next((a for a in assets if _SETUP_NAME.match(a.get("name", ""))), None)
    if setup is None:
        return None
    sha256 = _asset_sha256(setup, body)
    if not sha256:
        return None  # never install a file that cannot be checked
    manifest = next((a for a in assets if a.get("name") == MANIFEST_NAME), None)
    app_zip = next((a for a in assets if _APP_ZIP_NAME.match(a.get("name", ""))), None)
    return Release(
        tag=data.get("tag_name", ""),
        html_url=data.get("html_url", ""),
        setup_url=setup.get("browser_download_url", ""),
        setup_name=setup.get("name", ""),
        sha256=sha256,
        size=int(setup.get("size") or 0),
        manifest_url=manifest.get("browser_download_url", "") if manifest else "",
        manifest_sha256=_asset_sha256(manifest, "") if manifest else "",
        app_url=app_zip.get("browser_download_url", "") if app_zip else "",
        app_name=app_zip.get("name", "") if app_zip else "",
        app_sha256=_asset_sha256(app_zip, body) if app_zip else "",
        app_size=int(app_zip.get("size") or 0) if app_zip else 0,
    )


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


def _download(
    url: str,
    name: str,
    sha256: str,
    size: int,
    *,
    dest_dir: Path | None,
    progress: Callable[[int, int], None] | None,
    cancel: threading.Event | None,
) -> Path:
    """Download *url* to ``dest_dir/name`` and return the path, checked against *sha256*.

    The file is written as ``<name>.part`` and renamed only after the checksum
    matches, so a failed or cancelled download never leaves a usable file.
    """
    dest_dir = dest_dir or _update_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    part = final.with_name(final.name + ".part")
    try:
        digest = hashlib.sha256()
        done, total = 0, size
        req = urllib.request.Request(url, headers={"User-Agent": "OverlayTranslator-App"})
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
        if digest.hexdigest() != sha256:
            raise OSError(f"Checksum mismatch for the downloaded {name}")
        final.unlink(missing_ok=True)
        part.rename(final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return final


def _update_dir() -> Path:
    return Path(tempfile.gettempdir()) / "translator-overlay-update"


def download_setup(
    release: Release,
    *,
    dest_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download the release's installer and return its path, checked against SHA-256."""
    final = _download(
        release.setup_url,
        release.setup_name,
        release.sha256,
        release.size,
        dest_dir=dest_dir,
        progress=progress,
        cancel=cancel,
    )
    _logger.info("Downloaded update %s (%s)", release.tag, final)
    return final


# ── App-only update ───────────────────────────────────────────────────────────


def _safe_rel_path(rel: object) -> bool:
    """A relative POSIX path inside the install dir (no drive, no root, no ``..``)."""
    if not isinstance(rel, str) or not rel or "\\" in rel or ":" in rel:
        return False
    return not PurePosixPath(rel).is_absolute() and not {"", ".", ".."} & set(rel.split("/"))


def parse_manifest(text: str) -> dict | None:
    """A usable update manifest from its JSON text; None when anything is off."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    files = data.get("app_files")
    app_zip = data.get("app_zip")
    if (
        not all(isinstance(data.get(key), str) and data[key] for key in ("version", "deps_fingerprint", "runtime"))
        or not isinstance(files, list)
        or APP_EXE not in files
        or not all(_safe_rel_path(f) for f in files)
        or not isinstance(app_zip, dict)
        or not isinstance(app_zip.get("name"), str)
        or not isinstance(app_zip.get("sha256"), str)
    ):
        return None
    return data


def installed_manifest(app_dir: Path) -> dict | None:
    """The manifest the installer (or the last app-only update) put next to the exe."""
    try:
        return parse_manifest((app_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except OSError:
        return None


def fetch_manifest(release: Release) -> dict | None:
    """The release's update manifest; None when it has none or it cannot be read."""
    if not release.manifest_url:
        return None
    try:
        req = urllib.request.Request(release.manifest_url, headers={"User-Agent": "OverlayTranslator-App"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            raw = resp.read(_MANIFEST_MAX_BYTES + 1)
    except Exception as e:
        _logger.warning("Could not fetch the update manifest: %s", e)
        return None
    if len(raw) > _MANIFEST_MAX_BYTES:
        return None
    if hashlib.sha256(raw).hexdigest() != release.manifest_sha256:
        _logger.warning("Update manifest checksum mismatch")
        return None
    return parse_manifest(raw.decode("utf-8", errors="replace"))


def choose_update_path(
    installed: dict | None, new: dict | None, release: Release, app_version: str | None = None
) -> str:
    """"app" when only the app layer has to change, else "full" (the installer).

    The app zip is enough only when the installed deps layer is byte for byte the one
    the new release was built against (``deps_fingerprint`` hashes those files) on
    the same Python / PyInstaller (``runtime``), and the release's zip is the one its
    manifest describes.
    """
    app_version = app_version or getattr(config, "APP_VERSION", "")
    if installed is None or new is None:
        return "full"
    if installed["version"] != app_version or new["version"] != release.tag.lstrip("vV"):
        return "full"
    if installed["deps_fingerprint"] != new["deps_fingerprint"] or installed["runtime"] != new["runtime"]:
        return "full"
    if not (release.app_url and release.app_sha256):
        return "full"
    zip_info = new["app_zip"]
    if zip_info["name"] != release.app_name or zip_info["sha256"].lower() != release.app_sha256:
        return "full"
    return "app"


def download_app_zip(
    release: Release,
    manifest: dict,
    *,
    dest_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download the app zip, checked against SHA-256 and the manifest's file list."""
    final = _download(
        release.app_url,
        release.app_name,
        release.app_sha256,
        release.app_size,
        dest_dir=dest_dir,
        progress=progress,
        cancel=cancel,
    )
    try:
        with zipfile.ZipFile(final) as zf:
            names = sorted(n for n in zf.namelist() if not n.endswith("/"))
    except zipfile.BadZipFile:
        names = None
    if names != sorted(manifest["app_files"]):
        final.unlink(missing_ok=True)
        raise OSError("The app zip does not match its manifest")
    _logger.info("Downloaded app update %s (%s)", release.tag, final)
    return final


def app_update_plan(installed: dict, new: dict) -> tuple[list[str], list[str]]:
    """(files to put in place from the zip, old app files to remove), as relative paths.

    Windows paths ignore case: an old file whose name only changed case is the new
    file, and removing it would delete the new copy.
    """
    files = sorted(new["app_files"])
    kept = {f.casefold() for f in files}
    remove = sorted(f for f in set(installed["app_files"]) if f.casefold() not in kept)
    return files, remove


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ps_list(paths: list[str]) -> str:
    return "@(" + ", ".join(_ps_quote(p.replace("/", "\\")) for p in paths) + ")"


def app_waiter_script(
    *,
    app_dir: Path,
    zip_path: Path,
    manifest_path: Path,
    files: list[str],
    remove: list[str],
    version: str,
    pid: int,
    failed_marker: Path,
) -> str:
    """PowerShell that waits for *pid* to exit, then swaps the app-layer files.

    Every replaced or removed file is first renamed to ``<file>.old``; on any error
    the new files are deleted, the ``.old`` files are moved back, *failed_marker* is
    written (the next update of this version takes the full installer) and the old
    app starts again. Only after the swap succeeded the ``.old`` files go and the
    "Apps & features" version is set (its errors are ignored); then the new app starts.
    """
    q = _ps_quote
    return "\n".join(
        [
            f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue",
            "$ErrorActionPreference = 'Stop'",
            f"$app = {q(str(app_dir))}",
            f"$zip = {q(str(zip_path))}",
            f"$manifest = {q(str(manifest_path))}",
            f"$files = {_ps_list(files)}",
            f"$remove = {_ps_list(remove)}",
            "$stage = Join-Path $app '.update-staging'",
            "$swapped = $false",
            "$moved = New-Object System.Collections.Generic.List[string]",
            "$added = New-Object System.Collections.Generic.List[string]",
            "function Stash($rel) {",
            "  $p = Join-Path $app $rel",
            "  if (Test-Path -LiteralPath $p) {",
            "    Move-Item -LiteralPath $p -Destination \"$p.old\" -Force",
            "    $moved.Add($rel)",
            "  } else { $added.Add($rel) }",
            "}",
            "try {",
            "  if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }",
            "  Expand-Archive -LiteralPath $zip -DestinationPath $stage",
            "  foreach ($rel in $files) {",
            "    $dst = Join-Path $app $rel",
            "    Stash $rel",
            "    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null",
            "    Move-Item -LiteralPath (Join-Path $stage $rel) -Destination $dst",
            "  }",
            "  foreach ($rel in $remove) {",
            "    if (Test-Path -LiteralPath (Join-Path $app $rel)) { Stash $rel }",
            "  }",
            f"  Stash {q(MANIFEST_NAME)}",
            f"  Copy-Item -LiteralPath $manifest -Destination (Join-Path $app {q(MANIFEST_NAME)})",
            "  $swapped = $true",
            "} catch {",
            "  $ErrorActionPreference = 'Continue'",
            "  $err = $_ | Out-String",
            "  foreach ($rel in $added) { Remove-Item -LiteralPath (Join-Path $app $rel) -Force -ErrorAction SilentlyContinue }",
            "  foreach ($rel in $moved) {",
            "    $p = Join-Path $app $rel",
            "    Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue",
            "    Move-Item -LiteralPath \"$p.old\" -Destination $p -Force",
            "  }",
            f"  New-Item -ItemType Directory -Force -Path {q(str(failed_marker.parent))} | Out-Null",
            f"  Set-Content -LiteralPath {q(str(failed_marker))} -Value $err -Encoding UTF8",
            "}",
            "$ErrorActionPreference = 'Continue'",
            "if ($swapped) {",
            "  foreach ($rel in $moved) { Remove-Item -LiteralPath ((Join-Path $app $rel) + '.old') -Force -ErrorAction SilentlyContinue }",
            "  foreach ($root in 'HKCU:', 'HKLM:') {",
            f"    $key = $root + {q(chr(92) + _UNINSTALL_KEY)}",
            "    if (Test-Path -LiteralPath $key -ErrorAction SilentlyContinue) {",
            f"      Set-ItemProperty -LiteralPath $key -Name DisplayVersion -Value {q(version)} -ErrorAction SilentlyContinue",
            "    }",
            "  }",
            "}",
            "Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $zip, $manifest -Force -ErrorAction SilentlyContinue",
            f"Start-Process -FilePath (Join-Path $app {q(APP_EXE)})",
            "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
        ]
    )


def _marker_dir() -> Path:
    # The user data dir, not %TEMP%: a temp cleanup must not retry a failing swap.
    return Path(getattr(config, "USER_DATA_DIR", _update_dir())) / "update"


def _failed_marker(version: str) -> Path:
    """Marks *version* for the full installer: its app-only update failed once."""
    return _marker_dir() / f"app-update-failed-{version}.txt"


def _dir_writable(path: Path) -> bool:
    """The swap renames files in the install dir: an all-users install needs the setup."""
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def launch_app_update(prepared: PreparedUpdate, app_dir: Path, *, pid: int | None = None) -> None:
    """Write the swap script next to the zip and start it hidden; the caller quits next."""
    installed = installed_manifest(app_dir)
    if installed is None:
        raise OSError("The installed update manifest is gone")
    files, remove = app_update_plan(installed, prepared.manifest)
    work_dir = prepared.path.parent
    manifest_path = work_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(prepared.manifest, indent=1), encoding="utf-8")
    version = prepared.release.tag.lstrip("vV")
    script = app_waiter_script(
        app_dir=app_dir,
        zip_path=prepared.path,
        manifest_path=manifest_path,
        files=files,
        remove=remove,
        version=version,
        pid=pid or os.getpid(),
        failed_marker=_failed_marker(version),
    )
    # A file, not -EncodedCommand: ~650 paths exceed the 32K command line. UTF-8 with
    # a BOM, or Windows PowerShell 5.1 reads it in the ANSI code page.
    script_path = work_dir / "apply-update.ps1"
    script_path.write_text(script, encoding="utf-8-sig")
    _start_hidden_powershell(["-File", str(script_path)])
    _logger.info("App-only update %s scheduled after exit (%d files)", prepared.release.tag, len(files))


def prepare_update(
    *,
    app_dir: Path | None = None,
    dest_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> PreparedUpdate | None:
    """Download the latest release the light way if possible, else its installer.

    None when there is no newer release with a checkable installer. Any failure of
    the app-only path (manifest, download, checksum) falls back to the installer;
    a cancel is raised as ``DownloadCancelled``.
    """
    release = latest_release()
    if release is None:
        return None
    app_dir = app_dir or Path(sys.executable).resolve().parent
    version = release.tag.lstrip("vV")
    # The manifest decides which installed files are replaced or removed: unchecked
    # (no asset digest), it is not used.
    if (
        release.manifest_url
        and release.manifest_sha256
        and not _failed_marker(version).exists()
        and _dir_writable(app_dir)
    ):
        new = fetch_manifest(release)
        if choose_update_path(installed_manifest(app_dir), new, release) == "app":
            try:
                path = download_app_zip(release, new, dest_dir=dest_dir, progress=progress, cancel=cancel)
                return PreparedUpdate(release, path, new)
            except DownloadCancelled:
                raise
            except Exception as e:
                _logger.warning("App-only update failed, falling back to the installer: %s", e)
        else:
            _logger.info("Update %s needs the full installer", release.tag)
    return PreparedUpdate(release, download_setup(release, dest_dir=dest_dir, progress=progress, cancel=cancel))


def launch_update(prepared: PreparedUpdate, *, app_dir: Path | None = None, pid: int | None = None) -> None:
    """Schedule *prepared* to be applied once this process exits. Raises if it cannot.

    When an app-only update cannot be started, its version is marked so that the
    next try (the user clicks again) downloads the installer.
    """
    if not prepared.app_only:
        launch_installer(prepared.path, pid=pid)
        return
    try:
        launch_app_update(prepared, app_dir or Path(sys.executable).resolve().parent, pid=pid)
    except Exception as e:
        try:
            marker = _failed_marker(prepared.release.tag.lstrip("vV"))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"launch failed: {e}\n", encoding="utf-8")
        except OSError:
            pass
        raise


# ── Full installer ────────────────────────────────────────────────────────────


def waiter_script(setup: Path, pid: int) -> str:
    """PowerShell that waits for *pid* to exit, then runs *setup* silently."""
    args = ",".join(map(_ps_quote, INSTALLER_ARGS))
    return (
        f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath {_ps_quote(str(setup))} -ArgumentList {args}"
    )


def _start_hidden_powershell(args: list[str]) -> None:
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
            *args,
        ],
        creationflags=flags,
        close_fds=True,
    )


def launch_installer(setup: Path, *, pid: int | None = None) -> None:
    """Start the hidden waiter; the caller quits right after. Raises if it cannot start."""
    script = waiter_script(setup, pid or os.getpid())
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    _start_hidden_powershell(["-EncodedCommand", encoded])
    _logger.info("Update installer scheduled after exit: %s", setup)
