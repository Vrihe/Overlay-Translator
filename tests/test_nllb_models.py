"""
tests/test_nllb_models.py — published NLLB builds (HF tags) and their local copies.

Covers:
  • Tags are listed in natural version order (v2 before v10).
  • Local builds are matched to a tag by download marker or by directory name.
  • A download lands in nllb-<tag>, writes the marker, never overwrites an
    existing directory, and leaves nothing behind on a checksum mismatch.
"""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from translate import nllb_models
from translate.nllb_models import LocalModel, RemoteVersion

_REQUIRED = ("model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.bpe.model")


def _make_build(path: Path, marker_tag: str | None = None) -> Path:
    path.mkdir(parents=True)
    for name in _REQUIRED:
        (path / name).write_bytes(b"x")
    if marker_tag:
        (path / nllb_models.MARKER_FILE).write_text(json.dumps({"tag": marker_tag}))
    return path


class _FakeHub:
    """Stands in for urlopen: serves the refs, the file tree and file bodies."""

    def __init__(self, files: dict[str, bytes], bad_sha: str | None = None):
        self.files = files
        self.bad_sha = bad_sha

    def tree(self):
        entries = []
        for name, body in self.files.items():
            entry = {"type": "file", "path": name, "size": len(body)}
            if name == "model.bin":
                oid = "0" * 64 if self.bad_sha == name else hashlib.sha256(body).hexdigest()
                entry["lfs"] = {"oid": oid}
            entries.append(entry)
        return entries

    def __call__(self, req, timeout=None):
        url = req.full_url
        if "/tree/" in url:
            return io.BytesIO(json.dumps(self.tree()).encode())
        name = url.rsplit("/", 1)[1]
        return io.BytesIO(self.files[name])


class TestRemote(unittest.TestCase):
    def test_tags_in_natural_order(self):
        refs = {"tags": [{"name": n, "targetCommit": n + "-sha"} for n in ("v10-x", "v2-game", "v0-base", "v1-abbr")]}
        with patch.object(nllb_models, "_get_json", return_value=refs):
            tags = [v.tag for v in nllb_models.list_remote_versions("r/r")]
        self.assertEqual(tags, ["v0-base", "v1-abbr", "v2-game", "v10-x"])


class TestLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_complete_builds(self):
        _make_build(self.root / "nllb-v0-base")
        (self.root / "nllb-finetuned-v1-merged").mkdir()  # HF checkpoint, not CTranslate2
        with patch.object(nllb_models, "_models_roots", return_value=[self.root]):
            names = [m.path.name for m in nllb_models.list_local_models()]
        self.assertEqual(names, ["nllb-v0-base"])

    def test_match_by_marker_then_by_name(self):
        by_marker = LocalModel(self.root / "whatever", "v2-game")
        by_name = LocalModel(self.root / "nllb-v1-abbr-ct2-int8", None)
        local = [by_name, by_marker]
        self.assertIs(nllb_models.match_local("v2-game", local), by_marker)
        self.assertIs(nllb_models.match_local("v1-abbr", local), by_name)
        self.assertIsNone(nllb_models.match_local("v0-base", local))

    def test_name_match_needs_whole_tag(self):
        local = [LocalModel(self.root / "nllb-v1-abbreviated", None)]
        self.assertIsNone(nllb_models.match_local("v1-abbr", local))


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = {name: name.encode() * 10 for name in _REQUIRED}
        self.version = RemoteVersion("v1-abbr", "abc123")

    def tearDown(self):
        self.tmp.cleanup()

    def _download(self, hub):
        with patch.object(nllb_models.urllib.request, "urlopen", hub):
            return nllb_models.download_version(self.version, repo_id="r/r", dest_root=self.root)

    def test_downloads_into_tag_dir_with_marker(self):
        progress = []
        with patch.object(nllb_models.urllib.request, "urlopen", _FakeHub(self.files)):
            path = nllb_models.download_version(
                self.version,
                repo_id="r/r",
                dest_root=self.root,
                progress=lambda done, total: progress.append((done, total)),
            )
        self.assertEqual(path, self.root / "nllb-v1-abbr")
        self.assertEqual((path / "model.bin").read_bytes(), self.files["model.bin"])
        marker = json.loads((path / nllb_models.MARKER_FILE).read_text())
        self.assertEqual((marker["tag"], marker["sha"]), ("v1-abbr", "abc123"))
        total = sum(len(b) for b in self.files.values())
        self.assertEqual(progress[-1], (total, total))

    def test_existing_directory_is_kept(self):
        (self.root / "nllb-v1-abbr").mkdir()
        (self.root / "nllb-v1-abbr" / "mine.txt").write_text("keep")
        path = self._download(_FakeHub(self.files))
        self.assertEqual(path.name, "nllb-v1-abbr-2")
        self.assertTrue((self.root / "nllb-v1-abbr" / "mine.txt").exists())

    def test_checksum_mismatch_leaves_nothing(self):
        with self.assertRaises(OSError):
            self._download(_FakeHub(self.files, bad_sha="model.bin"))
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
