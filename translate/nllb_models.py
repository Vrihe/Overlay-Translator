"""
translate/nllb_models.py — the published NLLB builds and their local copies.

Every tag in the Hugging Face repo ``config.NLLB_HF_REPO_ID`` (``v0-base``,
``v1-abbr``, ``v2-game``, …) is one build of the model. This module lists those
tags, finds which of them are already on disk and downloads a missing one, so
the settings page can offer every build instead of only the newest local copy.

Only the standard library is used (the frozen app ships without
``huggingface_hub``). A tag is resolved to its commit SHA once and every file is
fetched from that SHA, so a tag moved mid-download cannot mix two builds; LFS
files are checked against their SHA-256 from the repo listing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import config
from translate.nllb_backend import _is_complete, _models_roots, missing_files

logger = logging.getLogger(__name__)

HF_ENDPOINT = "https://huggingface.co"

#: Written next to a downloaded build: {"repo_id", "tag", "sha"}.
MARKER_FILE = ".hf-version.json"

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
    ``progress(done_bytes, total_bytes)`` is called from the calling thread.
    """
    repo_id = repo_id or config.NLLB_HF_REPO_ID
    dest_root = dest_root or download_root()
    final = dest_root / f"nllb-{version.tag}"
    part = dest_root / f"nllb-{version.tag}.part"

    files = _repo_files(repo_id, version.sha)
    total = sum(int(f.get("size", 0)) for f in files)
    done = 0

    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    try:
        for entry in files:
            rel = entry["path"]
            target = part / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            expected_sha256 = (entry.get("lfs") or {}).get("oid")
            digest = hashlib.sha256()
            url = f"{HF_ENDPOINT}/{repo_id}/resolve/{version.sha}/{urllib.parse.quote(rel)}"
            req = urllib.request.Request(url, headers={"User-Agent": "translator-overlay"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp, open(target, "wb") as out:
                while chunk := resp.read(_CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
            if expected_sha256 and digest.hexdigest() != expected_sha256:
                raise OSError(f"Checksum mismatch for {rel}")

        missing = missing_files(part)
        if missing:
            raise OSError(f"Build {version.tag} lacks required files: {', '.join(missing)}")

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
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise

    logger.info("Downloaded NLLB build %s (%s) into %s", version.tag, version.sha[:7], final)
    return final
