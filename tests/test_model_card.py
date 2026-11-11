"""
tests/test_model_card.py — the Hugging Face model card generator (scripts/make_model_card.py).

Covers the card content (front matter, metrics, files, licence), the config summary and the CLI.
No network; the build directory is a temporary one.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_model_card", _ROOT / "scripts" / "make_model_card.py")
mc = importlib.util.module_from_spec(_spec)
sys.modules["make_model_card"] = mc
_spec.loader.exec_module(mc)

_MANIFEST = {
    "schema_version": 1,
    "version": "v2-game",
    "files": {"model.bin": {"sha256": "a" * 64, "size": 10}},
    "metrics": {"keep_rate": 96.4},
    "min_app_version": "1.4.0",
    "channel": "beta",
}


class TestCard(unittest.TestCase):
    def test_card_has_front_matter_metrics_files_and_licence(self):
        card = mc.build_card(_MANIFEST, config_path=None, data="DATA", limitations="LIM", reproduce="REPRO")
        self.assertTrue(card.startswith("---\nlicense: cc-by-nc-4.0\n"))
        for needle in ("v2-game", "| `keep_rate` | 96.4 |", "`model.bin`", "aaaaaaaaaaaa", "DATA", "LIM", "REPRO"):
            self.assertIn(needle, card)
        self.assertIn("`beta`", card)
        self.assertIn("`1.4.0`", card)

    def test_no_metrics_is_stated(self):
        card = mc.build_card({**_MANIFEST, "metrics": {}}, config_path=None, data="d", limitations="l", reproduce="r")
        self.assertIn("No metrics were recorded", card)

    def test_config_summary_reads_top_level_keys_and_ignores_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.yaml"
            cfg.write_text("# seed: 1\nname: v2b-game  # run\nseed: 42\nother: 5\n", encoding="utf-8")
            lines = mc._config_lines(cfg)
        self.assertEqual(lines, ["- `name`: `v2b-game`", "- `seed`: `42`"])


class TestCli(unittest.TestCase):
    def test_requires_manifest_then_writes_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(mc.main([str(root), "--data", "d"]), 1)
            (root / "manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")
            self.assertEqual(mc.main([str(root), "--data", "d"]), 0)
            self.assertIn("v2-game", (root / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
