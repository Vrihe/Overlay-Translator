"""
translate/model_manifest.py — the ``manifest.json`` published with every NLLB build.

The manifest sits in the root of the model repo at the tag's commit and describes that build:

    {
      "schema_version": 1,
      "version": "v2-game",
      "files": {"model.bin": {"sha256": "...", "size": 123}, ...},
      "metrics": {"chrf_general": 57.78, "keep_rate": 96.4},
      "min_app_version": "1.4.0",
      "channel": "stable"                      # "stable" | "beta"
    }

The app uses it to hide builds it is too old for and to prefer the ``stable`` channel;
file checksums are still checked by ``nllb_models`` against the Hub listing. Only the standard
library is used and nothing here runs during a translation. ``scripts/make_manifest.py`` writes it.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import config

SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
CHANNELS = ("stable", "beta")
_CHUNK = 1 << 20


class ManifestError(ValueError):
    """The manifest is not valid or not understood by this app."""


@dataclass(frozen=True)
class Manifest:
    version: str
    files: dict[str, dict] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    min_app_version: str = "0.0.0"
    channel: str = "stable"


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text.split("-")[0])
    if not parts:
        raise ManifestError(f"bad version: {text!r}")
    return tuple(int(p) for p in parts)


def parse_manifest(data: object) -> Manifest:
    """Validate a decoded manifest. Raises ``ManifestError`` with a short reason."""
    if not isinstance(data, dict):
        raise ManifestError("manifest is not an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"unsupported schema_version: {data.get('schema_version')!r}")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ManifestError("missing version")
    files = data.get("files")
    if not isinstance(files, dict) or "model.bin" not in files:
        raise ManifestError("files must list model.bin")
    for name, info in files.items():
        sha = info.get("sha256") if isinstance(info, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ManifestError(f"bad sha256 for {name}")
        if not isinstance(info.get("size"), int) or info["size"] < 0:
            raise ManifestError(f"bad size for {name}")
    channel = data.get("channel", "stable")
    if channel not in CHANNELS:
        raise ManifestError(f"unknown channel: {channel!r}")
    min_app = data.get("min_app_version", "0.0.0")
    _version_tuple(str(min_app))
    metrics = data.get("metrics", {})
    if not isinstance(metrics, dict) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in metrics.values()
    ):
        raise ManifestError("metrics must map names to numbers")
    return Manifest(version, files, dict(metrics), str(min_app), channel)


def is_compatible(manifest: Manifest, app_version: str | None = None) -> bool:
    """True when this app is at least ``min_app_version``."""
    return _version_tuple(app_version or config.APP_VERSION) >= _version_tuple(manifest.min_app_version)


def pick_default(candidates: dict[str, Manifest], app_version: str | None = None) -> str | None:
    """Tag to suggest: the newest compatible ``stable`` build (tags are in the given order, oldest first)."""
    usable = [tag for tag, m in candidates.items() if m.channel == "stable" and is_compatible(m, app_version)]
    return usable[-1] if usable else None


def fetch_manifest(sha: str, repo_id: str | None = None) -> Manifest:
    """Read the manifest of the commit *sha*. Raises on network errors and ``ManifestError``."""
    from translate import nllb_models

    repo_id = repo_id or config.NLLB_HF_REPO_ID
    url = f"{nllb_models.HF_ENDPOINT}/{repo_id}/resolve/{sha}/{urllib.parse.quote(MANIFEST_FILE)}"
    return parse_manifest(nllb_models._get_json(url))


def filter_compatible(versions: list, app_version: str | None = None, repo_id: str | None = None) -> list:
    """Drop the builds whose manifest says this app is too old for them.

    Best effort: a tag without a manifest (older builds) or one that cannot be read stays in the
    list, so a flaky network never empties the version picker. Order is kept.
    """
    kept = []
    for version in versions:
        try:
            manifest = fetch_manifest(version.sha, repo_id)
        except Exception:
            kept.append(version)
            continue
        if is_compatible(manifest, app_version):
            kept.append(version)
    return kept


def build_manifest(
    model_dir: Path,
    version: str,
    *,
    metrics: dict[str, float] | None = None,
    min_app_version: str = "0.0.0",
    channel: str = "stable",
) -> dict:
    """Manifest dict for the files of a build directory (checksums of every file except dotfiles)."""
    files = {}
    for path in sorted(p for p in Path(model_dir).rglob("*") if p.is_file() and not p.name.startswith(".")):
        rel = path.relative_to(model_dir).as_posix()
        if rel == MANIFEST_FILE:
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK):
                digest.update(chunk)
        files[rel] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
    data = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "files": files,
        "metrics": metrics or {},
        "min_app_version": min_app_version,
        "channel": channel,
    }
    parse_manifest(data)  # never write an invalid manifest
    return data


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
