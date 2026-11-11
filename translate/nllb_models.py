"""
translate/nllb_models.py — the published NLLB builds and their local copies.

Every tag in the Hugging Face repo ``config.NLLB_HF_REPO_ID`` (``v0-base``,
``v1-abbr``, ``v2-game``, …) is one build of the model. This module lists those
tags, finds which of them are already on disk and downloads a missing one, so
the settings page can offer every build instead of only the newest local copy.

Only the standard library is used (the frozen app ships without
``huggingface_hub``). A tag is resolved to its commit SHA once and every file is
fetched from that SHA, so a tag moved mid-download cannot mix two builds; LFS
files are checked against their SHA-256 from the repo listing. An interrupted
download (network error, cancel) keeps its ``.part`` directory and the next call
for the same commit resumes from the bytes already on disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import config
from translate.nllb_backend import _is_complete, _models_roots, missing_files

logger = logging.getLogger(__name__)

HF_ENDPOINT = "https://huggingface.co"

#: Written next to a downloaded build: {"repo_id", "tag", "sha"}.
MARKER_FILE = ".hf-version.json"

#: Written into a ``.part`` directory: the commit SHA its files belong to.
PART_MARKER = ".part-sha"

_TIMEOUT_SEC = 15
_CHUNK = 1 << 20


@dataclass(frozen=True)
class RemoteVersion:
    tag: str
    sha: str


@dataclass(frozen=True)
class LocalModel:
    path: Path
    tag: str | None  # HF tag this copy came from, when known


class DownloadCancelled(Exception):
    pass


# ── Remote ───────────────────────────────────────────────


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "translator-overlay"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        return json.load(resp)


def _tag_sort_key(tag: str):
    """Natural order, so ``v10`` comes after ``v2``."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", tag)]


def list_remote_versions(repo_id: str | None = None) -> list[RemoteVersion]:
    """All tags of the model repo, oldest version first. Raises on network errors."""
    repo_id = repo_id or config.NLLB_HF_REPO_ID
    refs = _get_json(f"{HF_ENDPOINT}/api/models/{repo_id}/refs")
    versions = [RemoteVersion(t["name"], t["targetCommit"]) for t in refs.get("tags", [])]
    return sorted(versions, key=lambda v: _tag_sort_key(v.tag))


# ── Local ────────────────────────────────────────────────


def download_root() -> Path:
    """Where new builds go: the project ``models`` dir in a dev checkout, the
    per-user one in the frozen app (its install dir may be read-only)."""
    roots = _models_roots()
    return roots[1] if getattr(sys, "frozen", False) else roots[0]


def _read_marker(path: Path) -> dict:
    try:
        return json.loads((path / MARKER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_local_models() -> list[LocalModel]:
    """Every complete CTranslate2 build in the ``models`` roots, sorted by name."""
    found: list[LocalModel] = []
    seen: set[str] = set()
    for root in _models_roots():
        try:
            dirs = sorted(p for p in root.iterdir() if _is_complete(p))
        except OSError:
            continue
        for path in dirs:
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(LocalModel(path, _read_marker(path).get("tag")))
    return found


def match_local(tag: str, local: list[LocalModel]) -> LocalModel | None:
    """The local copy of *tag*: by download marker, else by directory name
    (``nllb-v1-abbr-ct2-int8`` is a manual conversion of ``v1-abbr``)."""
    for model in local:
        if model.tag == tag:
            return model
    pattern = re.compile(rf"(^|[-_.]){re.escape(tag)}($|[-_.])", re.IGNORECASE)
    for model in local:
        if model.tag is None and pattern.search(model.path.name):
            return model
    return None


# ── Download ─────────────────────────────────────────────


def _repo_files(repo_id: str, sha: str) -> list[dict]:
    tree = _get_json(f"{HF_ENDPOINT}/api/models/{repo_id}/tree/{sha}?recursive=true")
    return [entry for entry in tree if entry.get("type") == "file"]


def resolve_revision(revision: str, repo_id: str | None = None) -> str:
    """Commit SHA of a tag, branch or SHA. Raises on network errors."""
    repo_id = repo_id or config.NLLB_HF_REPO_ID
    return _get_json(f"{HF_ENDPOINT}/api/models/{repo_id}/revision/{urllib.parse.quote(revision, safe='')}")["sha"]


def verify_build(path: Path, revision: str, repo_id: str | None = None) -> list[str]:
    """Check the files of a build on disk against the repo listing at *revision*.

    Returns the relative paths that are missing, have the wrong size or (LFS files) the wrong
    SHA-256; an empty list means the build is intact. Raises on network errors.
    """
    repo_id = repo_id or config.NLLB_HF_REPO_ID
    bad: list[str] = []
    for entry in _repo_files(repo_id, resolve_revision(revision, repo_id)):
        target = path / entry["path"]
        if not target.is_file() or target.stat().st_size != int(entry.get("size", 0)):
            bad.append(entry["path"])
            continue
        expected = (entry.get("lfs") or {}).get("oid")
        if expected:
            digest = hashlib.sha256()
            with open(target, "rb") as f:
                while chunk := f.read(_CHUNK):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                bad.append(entry["path"])
    return bad


def _fetch_file(
    url: str,
    target: Path,
    *,
    size: int,
    expected_sha256: str | None,
    on_bytes: Callable[[int], None],
    cancel: threading.Event | None,
) -> None:
    """Fetch *url* into *target*, resuming from the bytes already there; verify its SHA-256.

    A complete file on disk is only re-hashed; a partial one is continued with a ``Range``
    request (a server that ignores it sends 200 and the file is fetched again from the start).
    """
    digest = hashlib.sha256()
    have = target.stat().st_size if target.exists() else 0
    if size > 0 and have > size:
        target.unlink()
        have = 0
    if have and expected_sha256 is not None:
        with open(target, "rb") as f:
            while chunk := f.read(_CHUNK):
                digest.update(chunk)
    elif have and have < size:
        have = 0  # no checksum to resume against: start the file over
    if have == size and have > 0:
        if expected_sha256 and digest.hexdigest() != expected_sha256:
            target.unlink()
            raise OSError(f"Checksum mismatch for {target.name}")
        on_bytes(have)
        return

    headers = {"User-Agent": "translator-overlay"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        if have and getattr(resp, "status", 200) != 206:
            have, digest = 0, hashlib.sha256()  # Range ignored: the body is the whole file
        on_bytes(have)
        with open(target, "ab" if have else "wb") as out:
            while chunk := resp.read(_CHUNK):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                out.write(chunk)
                digest.update(chunk)
                on_bytes(len(chunk))
    if expected_sha256 and digest.hexdigest() != expected_sha256:
        target.unlink(missing_ok=True)
        raise OSError(f"Checksum mismatch for {target.name}")


def download_version(
    version: RemoteVersion,
    *,
    repo_id: str | None = None,
    dest_root: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download *version* into ``<dest_root>/nllb-<tag>`` (or ``nllb-<tag>-N`` when
    that name is taken) and return that path.

    Files go to a ``.part`` directory first and are moved into place only once
    all of them are fetched and verified, so a failed or cancelled download
    never leaves a half-written build that model discovery would pick up.
    The ``.part`` directory survives a network error or a cancel and the next call for
    the same commit resumes it; a checksum mismatch or a build lacking required files
    removes it. ``progress(done_bytes, total_bytes)`` is called from the calling thread.
    """
    repo_id = repo_id or config.NLLB_HF_REPO_ID
    dest_root = dest_root or download_root()
    final = dest_root / f"nllb-{version.tag}"
    part = dest_root / f"nllb-{version.tag}.part"

    files = _repo_files(repo_id, version.sha)
    total = sum(int(f.get("size", 0)) for f in files)
    done = 0

    def on_bytes(n: int) -> None:
        nonlocal done
        done += n
        if progress is not None:
            progress(done, total)

    try:
        same_commit = (part / PART_MARKER).is_file() and (part / PART_MARKER).read_text() == version.sha
    except OSError:
        same_commit = False
    if not same_commit:
        shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True, exist_ok=True)
    (part / PART_MARKER).write_text(version.sha, encoding="utf-8")
    try:
        for entry in files:
            rel = entry["path"]
            target = part / rel
            # The file list comes from the network: never write outside the build folder.
            if not target.resolve().is_relative_to(part.resolve()):
                raise OSError(f"Unsafe file path in build {version.tag}: {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"{HF_ENDPOINT}/{repo_id}/resolve/{version.sha}/{urllib.parse.quote(rel)}"
            _fetch_file(
                url,
                target,
                size=int(entry.get("size", 0)),
                expected_sha256=(entry.get("lfs") or {}).get("oid"),
                on_bytes=on_bytes,
                cancel=cancel,
            )

        missing = missing_files(part)
        if missing:
            raise OSError(f"Build {version.tag} lacks required files: {', '.join(missing)}")

        (part / PART_MARKER).unlink(missing_ok=True)
        (part / MARKER_FILE).write_text(
            json.dumps({"repo_id": repo_id, "tag": version.tag, "sha": version.sha}, indent=2),
            encoding="utf-8",
        )
        # Never overwrite an existing directory: it may be a manual conversion.
        n = 2
        while final.exists():
            final = dest_root / f"nllb-{version.tag}-{n}"
            n += 1
        part.rename(final)
    except (DownloadCancelled, urllib.error.URLError, TimeoutError, ConnectionError):
        raise  # keep the .part directory: the next attempt resumes it
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise

    logger.info("Downloaded NLLB build %s (%s) into %s", version.tag, version.sha[:7], final)
    return final
