"""
tests/test_model_manifest.py — the manifest.json of a model build (translate/model_manifest.py).

Covers validation, app-version compatibility, the default-build choice, building a manifest from a
directory, and reading one through a mocked Hub. No network.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from translate import model_manifest as mm

_SHA = "a" * 64


def _data(**over):
    data = {
        "schema_version": 1,
        "version": "v2-game",
        "files": {"model.bin": {"sha256": _SHA, "size": 10}},
        "metrics": {"keep_rate": 96.4},
        "min_app_version": "1.4.0",
        "channel": "stable",
    }
    data.update(over)
    return data


class TestParse(unittest.TestCase):
    def test_valid_manifest(self):
        m = mm.parse_manifest(_data())
        self.assertEqual((m.version, m.channel, m.min_app_version), ("v2-game", "stable", "1.4.0"))

    def test_defaults_for_optional_fields(self):
        data = _data()
        for key in ("channel", "min_app_version", "metrics"):
            del data[key]
        m = mm.parse_manifest(data)
        self.assertEqual((m.channel, m.min_app_version, m.metrics), ("stable", "0.0.0", {}))

    def test_rejects_bad_manifests(self):
        bad = [
            "text",
            _data(schema_version=2),
            _data(version=""),
            _data(files={}),
            _data(files={"model.bin": {"sha256": "xyz", "size": 1}}),
            _data(files={"model.bin": {"sha256": _SHA, "size": -1}}),
            _data(channel="nightly"),
            _data(min_app_version="latest"),
            _data(metrics={"chrf": "high"}),
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(mm.ManifestError):
                mm.parse_manifest(data)


class TestCompatibility(unittest.TestCase):
    def test_min_app_version(self):
        m = mm.parse_manifest(_data(min_app_version="1.5.0"))
        self.assertFalse(mm.is_compatible(m, "1.4.2"))
        self.assertTrue(mm.is_compatible(m, "1.5.0"))
        self.assertTrue(mm.is_compatible(m, "1.10.0"))  # numeric, not string, order

    def test_pick_default_is_newest_compatible_stable(self):
        builds = {
            "v1": mm.parse_manifest(_data(version="v1")),
            "v2": mm.parse_manifest(_data(version="v2")),
            "v3": mm.parse_manifest(_data(version="v3", channel="beta")),
            "v4": mm.parse_manifest(_data(version="v4", min_app_version="9.0.0")),
        }
        self.assertEqual(mm.pick_default(builds, "1.4.2"), "v2")
        self.assertIsNone(mm.pick_default({}, "1.4.2"))


class TestBuildAndFetch(unittest.TestCase):
    def test_build_hashes_files_and_skips_dotfiles_and_old_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.bin").write_bytes(b"abc")
            (root / "sub").mkdir()
            (root / "sub" / "x.json").write_bytes(b"{}")
            (root / ".hf-version.json").write_text("{}")
            (root / "manifest.json").write_text("old")
            data = mm.build_manifest(root, "v9", metrics={"a": 1}, channel="beta")
        self.assertEqual(sorted(data["files"]), ["model.bin", "sub/x.json"])
        self.assertEqual(data["files"]["model.bin"]["size"], 3)
        self.assertEqual(
            data["files"]["model.bin"]["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        self.assertEqual(mm.parse_manifest(json.loads(mm.dumps(data))).channel, "beta")

    def test_build_needs_model_bin(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(mm.ManifestError):
            mm.build_manifest(Path(tmp), "v1")

    def test_fetch_reads_manifest_at_the_commit(self):
        seen = []

        def fake(req, timeout=None):
            seen.append(req.full_url)
            return io.BytesIO(json.dumps(_data()).encode())

        with patch("translate.nllb_models.urllib.request.urlopen", fake):
            m = mm.fetch_manifest("deadbeef", repo_id="r/r")
        self.assertEqual(m.version, "v2-game")
        self.assertTrue(seen[0].endswith("/r/r/resolve/deadbeef/manifest.json"))


class TestFilterCompatible(unittest.TestCase):
    def test_hides_builds_that_need_a_newer_app_and_keeps_unreadable_ones(self):
        from translate.nllb_models import RemoteVersion

        versions = [RemoteVersion("v1", "s1"), RemoteVersion("v2", "s2"), RemoteVersion("v3", "s3")]

        def fake(sha, repo_id=None):
            if sha == "s1":
                raise OSError("404: no manifest")
            return mm.parse_manifest(_data(min_app_version="9.0.0" if sha == "s3" else "1.0.0"))

        with patch.object(mm, "fetch_manifest", fake):
            kept = mm.filter_compatible(versions, app_version="1.4.0")
        self.assertEqual([v.tag for v in kept], ["v1", "v2"])


if __name__ == "__main__":
    unittest.main()
