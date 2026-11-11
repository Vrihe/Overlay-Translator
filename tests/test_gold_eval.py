"""
tests/test_gold_eval.py — the hand-checked gold set scorer (training/gold_eval.py).

Covers schema validation, the training-leakage guard, per-category scores (chrF,
keep-rate, wrong-expansion rate, OCR-noise drop) and the mean / CI over seeds.
All rows are synthetic; metrics need sacrebleu.
"""

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

_TRAINING_DIR = Path(__file__).resolve().parent.parent / "training"


def _import_training(name: str):
    stub_pandas = importlib.util.find_spec("pandas") is None
    if stub_pandas:
        sys.modules["pandas"] = types.ModuleType("pandas")
    try:
        with mock.patch.object(sys, "path", [str(_TRAINING_DIR), *sys.path]):
            return importlib.import_module(name)
    finally:
        if stub_pandas:
            del sys.modules["pandas"]


gold_eval = _import_training("gold_eval")
_HAS_SACREBLEU = importlib.util.find_spec("sacrebleu") is not None


def _gold() -> list[dict]:
    return [
        {"id": "a", "src": "aaa one", "lang": "ru", "ref": "один а", "category": "abbr", "wrong_expansions": ["плохо"]},
        {
            "id": "b",
            "src": "bbb gg",
            "lang": "ru",
            "ref": "хорошая игра gg",
            "category": "keep",
            "keep_terms": ["gg"],
            "noisy_src": "bbb g9",
        },
        {"id": "c", "src": "the cat sleeps", "lang": "pl", "ref": "kot śpi", "category": "ordinary"},
        {"id": "d", "src": "the dog runs", "lang": "pl", "ref": "pies biegnie", "category": "ordinary"},
    ]


class TestValidation(unittest.TestCase):
    def test_valid_set_has_no_problems(self):
        self.assertEqual(gold_eval.validate_rows(_gold()), [])

    def test_reports_every_problem(self):
        rows = _gold()
        rows[0]["category"] = "slang"
        rows[1]["id"] = "a"
        rows[2]["lang"] = "xx"
        rows[3]["keep_terms"] = "gg"
        text = "\n".join(gold_eval.validate_rows(rows))
        self.assertIn("category must be one of", text)
        self.assertIn("duplicate id", text)
        self.assertIn("unsupported lang", text)
        self.assertIn("'keep_terms' must be a list", text)

    def test_noisy_src_must_differ(self):
        rows = _gold()
        rows[1]["noisy_src"] = rows[1]["src"]
        self.assertIn("not a distortion", "\n".join(gold_eval.validate_rows(rows)))

    def test_load_gold_raises_with_line_number_on_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            path.write_text('{"id": "a"}\nnot json\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"gold\.jsonl:2"):
                gold_eval.load_gold(path)

    def test_load_gold_round_trip_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _gold()) + "\n", encoding="utf-8")
            self.assertEqual(len(gold_eval.load_gold(path)), 4)
            first = gold_eval.gold_hash(path)
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            self.assertNotEqual(first, gold_eval.gold_hash(path))


class TestLeakGuard(unittest.TestCase):
    def test_flags_clean_and_noisy_sources_case_insensitively(self):
        train = [{"src": "THE  cat sleeps"}, {"src": "bbb g9"}, {"src": "unrelated"}]
        leaked = gold_eval.check_no_leak(_gold(), train)
        self.assertEqual(sorted(x.split(":")[0] for x in leaked), ["b", "c"])

    def test_clean_when_disjoint(self):
        self.assertEqual(gold_eval.check_no_leak(_gold(), [{"src": "something else"}]), [])


class TestHelpers(unittest.TestCase):
    def test_eval_rows_use_flores_codes_and_noisy_source(self):
        rows = gold_eval.to_eval_rows(_gold())
        self.assertEqual([r["tgt_code"] for r in rows], ["rus_Cyrl", "rus_Cyrl", "pol_Latn", "pol_Latn"])
        self.assertEqual(gold_eval.to_eval_rows(_gold()[1:2], noisy=True)[0]["src"], "bbb g9")

    def test_wrong_expansion_is_a_case_insensitive_substring(self):
        self.assertTrue(gold_eval.has_wrong_expansion("Это ПЛОХО", ["плохо"]))
        self.assertFalse(gold_eval.has_wrong_expansion("хорошо", ["плохо"]))

    def test_category_counts(self):
        counts = gold_eval.category_counts(_gold())
        self.assertEqual((counts["abbr"], counts["keep"], counts["ordinary"], counts["mixed"]), (1, 1, 2, 0))


@unittest.skipUnless(_HAS_SACREBLEU, "sacrebleu is not installed")
class TestScoring(unittest.TestCase):
    def test_perfect_system(self):
        rows = _gold()
        result = gold_eval.score_gold(rows, [r["ref"] for r in rows])
        self.assertEqual(result["chrf"], 100.0)
        self.assertEqual(result["keep_rate"], 100.0)
        self.assertEqual(result["wrong_expansion_rate"], 0.0)
        self.assertEqual(set(result["chrf_by_category"]), {"abbr", "keep", "ordinary"})
        self.assertEqual(set(result["chrf_by_lang"]), {"ru", "pl"})
        self.assertIsNone(result["ocr_noise"])

    def test_lost_keep_term_and_wrong_expansion(self):
        rows = _gold()
        hyps = [r["ref"] for r in rows]
        hyps[0] = "это плохо"
        hyps[1] = "хорошая игра"
        result = gold_eval.score_gold(rows, hyps)
        self.assertEqual(result["keep_rate"], 0.0)
        self.assertEqual(result["wrong_expansion_rate"], 100.0)
        self.assertLess(result["chrf_by_category"]["abbr"], 100.0)
        self.assertEqual(result["chrf_by_category"]["ordinary"], 100.0)

    def test_ocr_noise_drop_compares_clean_and_noisy_hypotheses(self):
        rows = _gold()
        hyps = [r["ref"] for r in rows]
        result = gold_eval.score_gold(rows, hyps, noisy_hyps={1: "???"})
        noise = result["ocr_noise"]
        self.assertEqual(noise["rows"], 1)
        self.assertEqual(noise["chrf_clean"], 100.0)
        self.assertGreater(noise["drop"], 50.0)


class TestAggregation(unittest.TestCase):
    def test_single_seed_has_no_interval(self):
        self.assertEqual(gold_eval.mean_ci([70.0]), {"n": 1, "mean": 70.0, "std": 0.0, "ci95": None})

    def test_three_seeds_use_the_t_value(self):
        result = gold_eval.mean_ci([60.0, 62.0, 64.0])
        self.assertEqual((result["n"], result["mean"], result["std"]), (3, 62.0, 2.0))
        self.assertAlmostEqual(result["ci95"], round(4.303 * 2.0 / 3**0.5, 2))

    def test_aggregate_flattens_scores_and_skips_missing_metrics(self):
        a = {
            "chrf": 50.0,
            "keep_rate": 90.0,
            "wrong_expansion_rate": None,
            "chrf_by_category": {"abbr": 40.0},
            "chrf_by_lang": {"ru": 55.0},
            "ocr_noise": {"drop": 5.0},
        }
        b = {**a, "chrf": 54.0, "keep_rate": 100.0}
        result = gold_eval.aggregate([a, b])
        self.assertEqual(result["chrf"]["mean"], 52.0)
        self.assertEqual(result["keep_rate"]["n"], 2)
        self.assertEqual(result["ocr_noise_drop"]["mean"], 5.0)
        self.assertNotIn("wrong_expansion_rate", result)
        self.assertIn("chrf[abbr]", result)
        self.assertIn("chrf[ru]", result)


class TestOcrNoise(unittest.TestCase):
    def test_noise_is_deterministic_and_differs(self):
        import random

        a = gold_eval.add_ocr_noise("need healer now", random.Random(1))
        b = gold_eval.add_ocr_noise("need healer now", random.Random(1))
        self.assertEqual(a, b)
        self.assertNotEqual(a, "need healer now")

    def test_fill_keeps_existing_noisy_src_and_validates(self):
        rows = _gold()
        rows[0]["noisy_src"] = "kept"
        had = sum(1 for r in rows if "noisy_src" in r)
        changed = gold_eval.fill_noisy_src(rows, seed=3)
        self.assertEqual(rows[0]["noisy_src"], "kept")
        self.assertEqual(changed, sum(1 for r in rows if "noisy_src" in r) - had)
        self.assertEqual(gold_eval.validate_rows(rows), [])


if __name__ == "__main__":
    unittest.main()
