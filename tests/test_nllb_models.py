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


class _Body(io.BytesIO):
    """A urlopen response: readable, with ``status`` and usable as a context manager."""

    status = 200


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

    ranges = True  # False: the server ignores Range and always sends the whole file

    def __call__(self, req, timeout=None):
        url = req.full_url
        if "/tree/" in url:
            return io.BytesIO(json.dumps(self.tree()).encode())
        if "/revision/" in url:
            return io.BytesIO(json.dumps({"sha": "abc123"}).encode())
        name = url.rsplit("/", 1)[1]
        self.requested = getattr(self, "requested", []) + [name]
        start = 0
        header = req.headers.get("Range")
        if header and self.ranges:
            start = int(header.split("=")[1].rstrip("-"))
        body = _Body(self.files[name][start:])
        body.status = 206 if start else 200
        return body


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


class _DownloadBase(unittest.TestCase):
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


class TestDownload(_DownloadBase):
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

    def test_path_outside_the_build_folder_is_refused(self):
        hub = _FakeHub({"../evil.txt": b"x", **self.files})
        with self.assertRaises(OSError):
            self._download(hub)
        self.assertFalse((self.root / "evil.txt").exists())
        self.assertEqual(list(self.root.iterdir()), [])


class _Dropped(_FakeHub):
    """Fails the connection after sending *cut* bytes of model.bin."""

    def __init__(self, files, cut):
        super().__init__(files)
        self.cut = cut

    def __call__(self, req, timeout=None):
        body = super().__call__(req, timeout)
        if req.full_url.endswith("model.bin") and not req.headers.get("Range"):

            class Broken(_Body):
                def read(inner, n=-1):
                    data = super(Broken, inner).read(self.cut)
                    if not data:
                        raise ConnectionError("dropped")
                    self.cut = 0
                    return data

            broken = Broken(body.getvalue())
            return broken
        return body


class TestResume(_DownloadBase):
    def _interrupted(self):
        with self.assertRaises(ConnectionError):
            self._download(_Dropped(self.files, cut=7))
        return self.root / "nllb-v1-abbr.part"

    def test_interrupted_download_keeps_part_and_resumes(self):
        part = self._interrupted()
        self.assertEqual((part / "model.bin").stat().st_size, 7)
        hub = _FakeHub(self.files)
        path = self._download(hub)
        self.assertEqual((path / "model.bin").read_bytes(), self.files["model.bin"])
        self.assertFalse(part.exists())
        self.assertFalse((path / nllb_models.PART_MARKER).exists())

    def test_resume_sends_a_range_request_for_the_missing_bytes(self):
        self._interrupted()
        hub = _FakeHub(self.files)
        ranges = []
        orig = hub.__call__

        def spy(req, timeout=None):
            if req.full_url.endswith("model.bin"):
                ranges.append(req.headers.get("Range"))
            return orig(req, timeout)

        with patch.object(nllb_models.urllib.request, "urlopen", spy):
            nllb_models.download_version(self.version, repo_id="r/r", dest_root=self.root)
        self.assertEqual(ranges, ["bytes=7-"])

    def test_server_without_range_support_still_finishes(self):
        self._interrupted()
        hub = _FakeHub(self.files)
        hub.ranges = False
        path = self._download(hub)
        self.assertEqual((path / "model.bin").read_bytes(), self.files["model.bin"])

    def test_part_of_another_commit_is_discarded(self):
        part = self._interrupted()
        self.version = RemoteVersion("v1-abbr", "other-sha")
        self._download(_FakeHub(self.files))
        self.assertFalse(part.exists())

    def test_corrupt_partial_file_fails_checksum_and_is_not_kept(self):
        part = self._interrupted()
        (part / "model.bin").write_bytes(b"garbage")  # same length class, wrong content
        with self.assertRaises(OSError):
            self._download(_FakeHub(self.files))
        self.assertFalse(part.exists())


class TestVerify(_DownloadBase):
    def _verify(self, path):
        with patch.object(nllb_models.urllib.request, "urlopen", _FakeHub(self.files)):
            return nllb_models.verify_build(path, "v1-abbr", repo_id="r/r")

    def test_intact_build_has_no_bad_files(self):
        path = self._download(_FakeHub(self.files))
        self.assertEqual(self._verify(path), [])

    def test_damaged_missing_and_short_files_are_reported(self):
        path = self._download(_FakeHub(self.files))
        (path / "model.bin").write_bytes(b"x" * len(self.files["model.bin"]))  # same size, wrong hash
        (path / "config.json").write_bytes(b"short")
        (path / "shared_vocabulary.json").unlink()
        self.assertEqual(sorted(self._verify(path)), ["config.json", "model.bin", "shared_vocabulary.json"])


if __name__ == "__main__":
    unittest.main()
