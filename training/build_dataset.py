"""
training/build_dataset.py — stages 2.3-2.5 of the NLLB fine-tune: build the
train/val/test pairs.

Inputs
  data/interim/abbr_phrases.jsonl       (training/abbr_phrases.py)
  data/interim/abbr_translations.jsonl  (training/translate_phrases.py)
  data/raw/flores200/data/language/<code>/dev-*.parquet  (facebook/flores, CC-BY-SA-4.0)

Pairs
  * kind=abbr    : phrase WITH the abbreviation -> NLLB translation of the FULL phrase.
                   Translations that dropped a "keep" term (keep_ok == false) are skipped.
  * kind=general : FLORES-200 dev sentence (eng_Latn) -> reference translation.
                   They make up ~30 % of every split so the model keeps its general skill.

Split (fixed seed), ``--split-by``
  * ``abbr`` (default, held-out experiment): abbreviations, not phrases, are split: ~15 % go to test, ~10 % to val, stratified
    by mode (keep / translate). A phrase whose short form contains a test
    abbreviation goes to test, else one with a val abbreviation goes to val, so no
    test abbreviation ever appears in train or val.
  * ``phrase`` (final model): every abbreviation is trained on; one phrase per
    abbreviation goes to test and one more (if it has 4+) to val, so the test
    checks known abbreviations in unseen phrases.
  * FLORES sentences are split into disjoint train / val / test pools.

Output: data/processed/{train,val,test}.jsonl, one pair per line::

    {"src": "brb, doorbell", "tgt": "...", "lang": "ru", "tgt_code": "rus_Cyrl",
     "kind": "abbr", "abbrs": ["brb"], "mode": "translate"}

Usage
-----
    python training/build_dataset.py
    python training/build_dataset.py --seed 42 --general-share 0.3
    python training/build_dataset.py --split-by phrase --out-dir data/processed_final
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTERIM = _PROJECT_ROOT / "data" / "interim"
FLORES_DIR = _PROJECT_ROOT / "data" / "raw" / "flores200" / "data" / "language"
OUT_DIR = _PROJECT_ROOT / "data" / "processed"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate_phrases import LANGS  # noqa: E402

SPLITS = ("train", "val", "test")
# Share of FLORES dev sentences in each pool (the pools never overlap).
FLORES_POOLS = {"train": 0.7, "val": 0.1, "test": 0.2}


def words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[\w']+", text)}


def split_abbreviations(phrases: list[dict], rng: random.Random,
                        test_share: float, val_share: float) -> dict[str, str]:
    """abbr -> split, stratified by mode."""
    assignment: dict[str, str] = {}
    for mode in ("keep", "translate"):
        abbrs = sorted({p["abbr"].lower() for p in phrases if p["mode"] == mode})
        rng.shuffle(abbrs)
        n_test = round(len(abbrs) * test_share)
        n_val = round(len(abbrs) * val_share)
        for i, a in enumerate(abbrs):
            assignment[a] = "test" if i < n_test else "val" if i < n_test + n_val else "train"
    return assignment


def split_phrases(phrases: list[dict], rng: random.Random) -> dict[str, str]:
    """short phrase -> split: per abbreviation one phrase to test, one more to val if it has 4+."""
    sections: dict[str, list[str]] = {}
    for p in phrases:
        sections.setdefault(p["abbr"].lower(), []).append(p["short"])
    assignment = {}
    for abbr in sorted(sections):
        shorts = sorted(sections[abbr])
        rng.shuffle(shorts)
        for i, short in enumerate(shorts):
            assignment[short] = "test" if i == 0 else "val" if i == 1 and len(shorts) >= 4 else "train"
    return assignment


def phrase_split(phrase: dict, assignment: dict[str, str]) -> tuple[str, list[str]]:
    """Split of a phrase and every known abbreviation it contains."""
    found = sorted(words(phrase["short"]) & assignment.keys())
    splits = {assignment[a] for a in found}
    split = "test" if "test" in splits else "val" if "val" in splits else "train"
    return split, found


def load_flores(path: Path = FLORES_DIR) -> dict[str, list[str]]:
    """NLLB code -> dev sentences (aligned by index)."""
    out = {}
    for code in ["eng_Latn", *LANGS.values()]:
        files = sorted((path / code).glob("dev-*.parquet"))
        if not files:
            raise FileNotFoundError(f"FLORES dev for {code} not found in {path / code}")
        df = pd.concat(pd.read_parquet(f) for f in files)
        column = "sentence" if "sentence" in df.columns else "text"
        out[code] = df[column].tolist()
    sizes = {len(v) for v in out.values()}
    if len(sizes) != 1:
        raise ValueError(f"FLORES dev files are not aligned: {sizes}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build train/val/test pairs for the abbreviation fine-tune.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-share", type=float, default=0.15, help="share of abbreviations held out for test")
    parser.add_argument("--val-share", type=float, default=0.10, help="share of abbreviations held out for val")
    parser.add_argument("--split-by", choices=("abbr", "phrase"), default="abbr")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--general-share", type=float, default=0.30, help="share of general pairs in every split")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    phrases = [json.loads(l) for l in (INTERIM / "abbr_phrases.jsonl").read_text(encoding="utf-8").splitlines()]
    translations = {}
    for line in (INTERIM / "abbr_translations.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        translations[(row["full"], row["lang"])] = row

    missing = {(p["full"], lang) for p in phrases for lang in LANGS} - translations.keys()
    if missing:
        print(f"{len(missing)} phrase translations are missing; run training/translate_phrases.py first",
              file=sys.stderr)
        return 1

    # Always drawn first, so the FLORES pools below are identical for both --split-by modes
    # and the general test set stays comparable across runs.
    assignment = split_abbreviations(phrases, rng, args.test_share, args.val_share)
    by_phrase = split_phrases(phrases, random.Random(args.seed + 1)) if args.split_by == "phrase" else None
    pairs: dict[str, list[dict]] = {s: [] for s in SPLITS}
    dropped = Counter()
    for p in phrases:
        split, found = phrase_split(p, assignment)
        if by_phrase is not None:
            split = by_phrase[p["short"]]
        for lang, code in LANGS.items():
            tr = translations[(p["full"], lang)]
            if not tr["keep_ok"]:
                dropped[lang] += 1
                continue
            pairs[split].append({"src": p["short"], "tgt": tr["text"], "lang": lang, "tgt_code": code,
                                 "kind": "abbr", "abbrs": found, "mode": p["mode"]})

    flores = load_flores()
    ids = list(range(len(flores["eng_Latn"])))
    rng.shuffle(ids)
    n_train = round(len(ids) * FLORES_POOLS["train"])
    n_val = round(len(ids) * FLORES_POOLS["val"])
    pools = {"train": ids[:n_train], "val": ids[n_train:n_train + n_val], "test": ids[n_train + n_val:]}

    for split in SPLITS:
        need = round(len(pairs[split]) * args.general_share / (1 - args.general_share))
        candidates = [(i, lang) for i in pools[split] for lang in LANGS]
        rng.shuffle(candidates)
        if need > len(candidates):
            print(f"[{split}] only {len(candidates)} general pairs available, need {need}", file=sys.stderr)
        for i, lang in candidates[:need]:
            pairs[split].append({"src": flores["eng_Latn"][i], "tgt": flores[LANGS[lang]][i], "lang": lang,
                                 "tgt_code": LANGS[lang], "kind": "general", "abbrs": [], "mode": None,
                                 "flores_id": i})

    # No test abbreviation may leak into train/val sources.
    test_abbrs = {a for a, s in assignment.items() if s == "test"}
    for split in ("train", "val") if by_phrase is None else ():
        leaked = {a for row in pairs[split] if row["kind"] == "abbr" for a in row["abbrs"]} & test_abbrs
        assert not leaked, f"test abbreviations leaked into {split}: {leaked}"

    out_dir = args.out_dir if args.out_dir.is_absolute() else _PROJECT_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        rng.shuffle(pairs[split])
        with (out_dir / f"{split}.jsonl").open("w", encoding="utf-8") as f:
            for row in pairs[split]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"seed={args.seed}, split by {args.split_by}; dropped {sum(dropped.values())} abbr pairs with lost keep terms: {dict(dropped)}")
    for split in SPLITS:
        kinds = Counter(r["kind"] for r in pairs[split])
        if by_phrase is None:
            abbrs = sorted(a for a, s in assignment.items() if s == split)
            detail = f"{len(abbrs)} abbreviations" + (f": {' '.join(abbrs)}" if split != "train" else "")
        else:
            detail = f"{sum(s == split for s in by_phrase.values())} phrases"
        print(f"{split:5}: {len(pairs[split]):5} pairs (abbr {kinds['abbr']}, general {kinds['general']}); {detail}")
    print(f"Saved to {out_dir.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
