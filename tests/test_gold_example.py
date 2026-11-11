"""
tests/test_gold_example.py — the format example for the gold set (training/gold_example.jsonl).

The example rows are synthetic and only show the schema; they must stay valid for
``gold_eval.py`` and must never be mistaken for real evaluation data.
"""

import json
import sys
import unittest
from pathlib import Path

_TRAINING = Path(__file__).resolve().parent.parent / "training"
if str(_TRAINING) not in sys.path:
    sys.path.insert(0, str(_TRAINING))

import gold_eval  # noqa: E402

_EXAMPLE = _TRAINING / "gold_example.jsonl"


class TestGoldExample(unittest.TestCase):
    def setUp(self):
        self.rows = [json.loads(line) for line in _EXAMPLE.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_is_valid(self):
        self.assertEqual(gold_eval.validate_rows(self.rows), [])

    def test_covers_every_category(self):
        self.assertEqual({r["category"] for r in self.rows}, set(gold_eval.CATEGORIES))

    def test_ids_are_marked_as_examples(self):
        self.assertTrue(all(r["id"].startswith("example-") for r in self.rows))

    def test_example_is_below_the_recommended_size(self):
        # keeps `validate` warning if the example is ever copied to data/gold/ by mistake
        self.assertLess(len(self.rows), gold_eval.MIN_RECOMMENDED_ROWS)


if __name__ == "__main__":
    unittest.main()
