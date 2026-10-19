"""
training/build_dataset_v2.py — stage 2 of the v2 fine-tune: v1 release data +
curated game-glossary phrases + more FLORES-200.

Inputs
  data/processed_final/{train,val,test}.jsonl   v1 release splits (reused unchanged)
  data/interim/v2/game_phrases.jsonl            (training/game_abbreviations.py)
  data/interim/v2/game_translations.jsonl       (training/translate_phrases.py --input ... [--repair-keep])
  data/raw/flores200/...                        FLORES-200 dev

The FLORES train / val / test pools are recomputed exactly as in
``build_dataset.py`` (same seed, same draw order), so the general test set is the one
v1 was scored on and no FLORES test sentence is ever trained on. v1 used ~15 % of the
train pool; v2 has ~5x more phrase pairs, so more of the pool is added to keep general
pairs at ``--general-share`` of train (the stand-in against catastrophic forgetting).

Pairs whose translation lost a keep term (``keep_ok == false`` after the repair pass)
are dropped, as in v1.

Output: data/processed_v2/
  train.jsonl, val.jsonl   v1 + v2 pairs
  test_v1.jsonl            v1 release test set, unchanged (regression check)
  test_v2.jsonl            v2 glossary test: template sentences, held-out examples, plain words

Usage
-----
    python training/build_dataset_v2.py
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dataset import FLORES_POOLS, load_flores, split_abbreviations  # noqa: E402
from translate_phrases import LANGS  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
V1_DIR = _PROJECT_ROOT / "data" / "processed_final"
V1_PHRASES = _PROJECT_ROOT / "data" / "interim" / "abbr_phrases.jsonl"
V2_INTERIM = _PROJECT_ROOT / "data" / "interim" / "v2"
OUT_DIR = _PROJECT_ROOT / "data" / "processed_v2"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def flores_pools(seed: int, n_sentences: int) -> dict[str, list[int]]:
    """The FLORES id pools of build_dataset.py: the abbreviation split is drawn first from the same rng."""
    rng = random.Random(seed)
    split_abbreviations(load_jsonl(V1_PHRASES), rng, 0.15, 0.10)
    ids = list(range(n_sentences))
    rng.shuffle(ids)
    n_train = round(len(ids) * FLORES_POOLS["train"])
    n_val = round(len(ids) * FLORES_POOLS["val"])
    return {"train": ids[:n_train], "val": ids[n_train:n_train + n_val], "test": ids[n_train + n_val:]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the v2 train/val/test pairs.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--general-share", type=float, default=0.25, help="target share of FLORES pairs in train")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    v1 = {s: load_jsonl(V1_DIR / f"{s}.jsonl") for s in ("train", "val", "test")}
    phrases = load_jsonl(V2_INTERIM / "game_phrases.jsonl")
    translations = {(r["full"], r["lang"]): r for r in load_jsonl(V2_INTERIM / "game_translations.jsonl")}

    pairs: dict[str, list[dict]] = {"train": list(v1["train"]), "val": list(v1["val"]), "test": []}
    dropped, missing = Counter(), 0
    for p in phrases:
        for lang in p["langs"]:
            tr = translations.get((p["full"], lang))
            if tr is None:
                missing += 1
                continue
            if not tr["keep_ok"]:
                dropped[p["split"]] += 1
                continue
            pairs[p["split"]].append({
                "src": p["short"], "tgt": tr["text"], "lang": lang, "tgt_code": LANGS[lang], "kind": "abbr",
                "abbrs": sorted({*map(str.lower, p["keep_terms"]), *p["expanded"]}), "mode": p["mode"],
                "keep_terms": p["keep_terms"], "origin": p["origin"], "set": "v2"})
    if missing:
        print(f"{missing} phrase translations are missing; run training/translate_phrases.py first",
              file=sys.stderr)
        return 1

    # More FLORES from the train pool only; v1 train already holds part of it.
    flores = load_flores()
    pools = flores_pools(args.seed, len(flores["eng_Latn"]))
    used = {(r["flores_id"], r["lang"]) for r in v1["train"] if r["kind"] == "general"}
    pool_ids = set(pools["train"])
    assert all(i in pool_ids for i, _ in used), "v1 train FLORES ids are outside the recomputed train pool"
    rng = random.Random(args.seed)
    candidates = [(i, lang) for i in pools["train"] for lang in LANGS if (i, lang) not in used]
    rng.shuffle(candidates)
    n_abbr = sum(r["kind"] == "abbr" for r in pairs["train"])
    need = round(n_abbr * args.general_share / (1 - args.general_share)) - len(used)
    if need > len(candidates):
        print(f"only {len(candidates)} more general pairs available, need {need}", file=sys.stderr)
    for i, lang in candidates[:max(need, 0)]:
        pairs["train"].append({"src": flores["eng_Latn"][i], "tgt": flores[LANGS[lang]][i], "lang": lang,
                               "tgt_code": LANGS[lang], "kind": "general", "abbrs": [], "mode": None,
                               "flores_id": i})

    # v2 test phrases must not be trained on in any spelling
    test_src = {r["src"].lower() for r in pairs["test"]} | {r["src"].lower() for r in v1["test"]}
    for split in ("train", "val"):
        leaked = {r["src"] for r in pairs[split] if r["kind"] == "abbr" and r["src"].lower() in test_src}
        assert not leaked, f"test phrases leaked into {split}: {sorted(leaked)[:10]}"

    out_dir = args.out_dir if args.out_dir.is_absolute() else _PROJECT_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for split, name in (("train", "train"), ("val", "val"), ("test", "test_v2")):
        rng.shuffle(pairs[split])
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for row in pairs[split]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shutil.copyfile(V1_DIR / "test.jsonl", out_dir / "test_v1.jsonl")

    print(f"dropped {sum(dropped.values())} v2 pairs with lost keep terms: {dict(dropped)}")
    for split, rows in pairs.items():
        kinds = Counter((r.get("set", "v1"), r["kind"]) for r in rows)
        print(f"{split:5}: {len(rows):6} pairs {dict(sorted(kinds.items()))}")
    general = sum(r["kind"] == "general" for r in pairs["train"]) / len(pairs["train"])
    print(f"general share in train: {general:.1%}; test_v1: {len(v1['test'])} pairs (copied)")
    print(f"Saved to {out_dir.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
