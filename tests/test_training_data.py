"""
tests/test_training_data.py — dataset splits and evaluation metrics of the NLLB fine-tune.

Covers:
  • training/build_dataset.py: the abbreviation split is stratified and reproducible,
    and no test (or val) abbreviation leaks into a train phrase; the phrase split puts
    exactly one phrase per abbreviation into test;
  • training/build_dataset_v2.py: the FLORES pools are disjoint and cover every sentence;
  • training/evaluate.py: keep-rate matching, chrF grouping and the paired bootstrap.
The phrases are synthetic. pandas is only needed to read FLORES parquet files, so the
module is imported with a stub when pandas is missing; the metrics need sacrebleu.
"""

import importlib
import importlib.util
import random
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_TRAINING_DIR = Path(__file__).resolve().parent.parent / "training"


def _import_training(name: str):
    # Not mock.patch.dict(sys.modules): restoring it would also unload numpy, which
    # cannot be imported twice in one process.
    stub_pandas = importlib.util.find_spec("pandas") is None
    if stub_pandas:
        sys.modules["pandas"] = types.ModuleType("pandas")
    try:
        with mock.patch.object(sys, "path", [str(_TRAINING_DIR), *sys.path]):
            return importlib.import_module(name)
    finally:
        if stub_pandas:
            del sys.modules["pandas"]


build_dataset = _import_training("build_dataset")
build_dataset_v2 = _import_training("build_dataset_v2")
evaluate = _import_training("evaluate")

_HAS_SACREBLEU = importlib.util.find_spec("sacrebleu") is not None


def _phrases(n_keep=20, n_translate=40, per_abbr=3) -> list[dict]:
    phrases = []
    for mode, count in (("keep", n_keep), ("translate", n_translate)):
        for i in range(count):
            abbr = f"{mode[0]}{i}x"
            for j in range(per_abbr):
                phrases.append({"abbr": abbr, "mode": mode, "short": f"say {abbr} now {j}", "full": f"full {abbr} {j}"})
    return phrases


class TestAbbreviationSplit(unittest.TestCase):
    def test_shares_are_stratified_by_mode(self):
        phrases = _phrases()
        assignment = build_dataset.split_abbreviations(phrases, random.Random(1), 0.15, 0.10)
        for mode, total in (("keep", 20), ("translate", 40)):
            splits = [s for a, s in assignment.items() if a.startswith(mode[0])]
            self.assertEqual(len(splits), total)
            self.assertEqual(splits.count("test"), round(total * 0.15))
            self.assertEqual(splits.count("val"), round(total * 0.10))

    def test_same_seed_same_split(self):
        phrases = _phrases()
        first = build_dataset.split_abbreviations(phrases, random.Random(42), 0.15, 0.10)
        again = build_dataset.split_abbreviations(list(reversed(phrases)), random.Random(42), 0.15, 0.10)
        self.assertEqual(first, again, "the split must not depend on the input order")

    def test_no_held_out_abbreviation_leaks_into_train(self):
        phrases = _phrases()
        # Lines that mix abbreviations of different splits.
        phrases.append({"abbr": "k0x", "mode": "keep", "short": "k0x and t0x and k1x", "full": "-"})
        phrases.append({"abbr": "t5x", "mode": "translate", "short": "T5X, t6x!", "full": "-"})
        assignment = build_dataset.split_abbreviations(phrases, random.Random(7), 0.15, 0.10)

        by_split: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}
        for phrase in phrases:
            split, found = build_dataset.phrase_split(phrase, assignment)
            self.assertEqual(found, sorted(build_dataset.words(phrase["short"]) & assignment.keys()))
            by_split[split].update(found)

        test_abbrs = {a for a, s in assignment.items() if s == "test"}
        val_abbrs = {a for a, s in assignment.items() if s == "val"}
        self.assertFalse(test_abbrs & (by_split["train"] | by_split["val"]), "test abbreviation outside test")
        self.assertFalse(val_abbrs & by_split["train"], "val abbreviation in train")

    def test_phrase_split_prefers_test_then_val(self):
        assignment = {"aa": "train", "bb": "val", "cc": "test"}
        self.assertEqual(build_dataset.phrase_split({"short": "aa bb"}, assignment), ("val", ["aa", "bb"]))
        self.assertEqual(build_dataset.phrase_split({"short": "BB, cc"}, assignment), ("test", ["bb", "cc"]))
        self.assertEqual(build_dataset.phrase_split({"short": "nothing"}, assignment), ("train", []))


class TestPhraseSplit(unittest.TestCase):
    def test_one_test_phrase_per_abbreviation_and_val_only_from_four(self):
        phrases = _phrases(n_keep=5, n_translate=5, per_abbr=3) + [
            {"abbr": "big", "mode": "keep", "short": f"big {j}", "full": "-"} for j in range(4)
        ]
        assignment = build_dataset.split_phrases(phrases, random.Random(3))
        self.assertEqual(len(assignment), len(phrases))
        for abbr in {p["abbr"] for p in phrases}:
            splits = [assignment[p["short"]] for p in phrases if p["abbr"] == abbr]
            self.assertEqual(splits.count("test"), 1, abbr)
            self.assertEqual(splits.count("val"), 1 if len(splits) >= 4 else 0, abbr)


class TestFloresPools(unittest.TestCase):
    def test_pools_are_disjoint_and_complete(self):
        with mock.patch.object(build_dataset_v2, "load_jsonl", return_value=_phrases()):
            pools = build_dataset_v2.flores_pools(42, 997)
            again = build_dataset_v2.flores_pools(42, 997)
        self.assertEqual(pools, again)
        ids = pools["train"] + pools["val"] + pools["test"]
        self.assertEqual(sorted(ids), list(range(997)), "every sentence in exactly one pool")
        self.assertEqual(len(pools["train"]), round(997 * build_dataset.FLORES_POOLS["train"]))


class TestKeepRate(unittest.TestCase):
    def test_terms_must_survive_as_whole_words(self):
        self.assertTrue(evaluate.keep_ok("хорошая игра, GG", ["gg"]))
        self.assertTrue(evaluate.keep_ok("pvp и afk", ["pvp", "afk"]))
        self.assertFalse(evaluate.keep_ok("eggs", ["gg"]), "a term inside a word does not count")
        self.assertFalse(evaluate.keep_ok("pvp", ["pvp", "afk"]))
        self.assertTrue(evaluate.keep_ok("anything", []))

    def test_by_lang_groups_row_indexes(self):
        rows = [{"tgt_code": "rus_Cyrl"}, {"tgt_code": "pol_Latn"}, {"tgt_code": "rus_Cyrl"}]
        self.assertEqual(dict(evaluate.by_lang(rows)), {"rus_Cyrl": [0, 2], "pol_Latn": [1]})


def _rows() -> list[dict]:
    return [
        {"kind": "abbr", "mode": "keep", "abbrs": ["gg"], "lang": "ru", "tgt": "gg, хорошая игра"},
        {"kind": "abbr", "mode": "translate", "abbrs": ["brb"], "lang": "ru", "tgt": "скоро вернусь"},
        {"kind": "abbr", "mode": "keep", "abbrs": ["pvp"], "lang": "pl", "tgt": "pvp jutro"},
        {"kind": "general", "mode": "", "abbrs": [], "lang": "ru", "tgt": "кошка спит на окне"},
        {"kind": "general", "mode": "", "abbrs": [], "lang": "pl", "tgt": "kot śpi na oknie"},
    ]


@unittest.skipUnless(_HAS_SACREBLEU, "sacrebleu is not installed")
class TestScore(unittest.TestCase):
    def test_perfect_hypotheses(self):
        rows = _rows()
        result = evaluate.score(rows, [r["tgt"] for r in rows], keep_terms={"gg", "pvp"})
        self.assertEqual(result["chrf"], {"abbr": 100.0, "general": 100.0})
        self.assertEqual(result["keep_rate"], 100.0)
        self.assertEqual(set(result["chrf_by_mode"]), {"keep", "translate"})
        self.assertEqual(result["chrf_by_lang"]["general"], {"pl": 100.0, "ru": 100.0})

    def test_lost_keep_term_lowers_keep_rate(self):
        rows = _rows()
        hyps = [r["tgt"] for r in rows]
        hyps[0] = "хорошая игра"  # "gg" lost
        result = evaluate.score(rows, hyps, keep_terms={"gg", "pvp"})
        self.assertEqual(result["keep_rate"], 50.0)
        self.assertLess(result["chrf"]["abbr"], 100.0)
        self.assertEqual(result["chrf"]["general"], 100.0)

    def test_v2_rows_list_their_own_keep_terms(self):
        rows = _rows()
        rows[1]["keep_terms"] = ["brb"]  # a translate-mode line with a term to keep
        hyps = [r["tgt"] for r in rows]
        result = evaluate.score(rows, hyps, keep_terms={"gg", "pvp"})
        self.assertEqual(result["keep_rate"], round(100 * 2 / 3, 1))

    def test_bootstrap_of_identical_systems_is_zero(self):
        rows = _rows()
        hyps = [r["tgt"] for r in rows]
        self.assertEqual(evaluate.bootstrap_delta(rows, hyps, hyps, [0, 1, 2], n=50), (0.0, 0.0, 0.0))

    def test_bootstrap_sign_follows_the_better_system(self):
        rows = _rows()
        good = [r["tgt"] for r in rows]
        bad = ["???" for _ in rows]
        delta, low, high = evaluate.bootstrap_delta(rows, bad, good, [0, 1, 2, 3, 4], n=200)
        self.assertGreater(delta, 0)
        self.assertLessEqual(low, delta)
        self.assertGreaterEqual(high, delta)


if __name__ == "__main__":
    unittest.main()
