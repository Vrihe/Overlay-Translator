"""
training/gold_eval.py — roadmap stage 4: score NLLB systems on a hand-checked "gold" set.

``training/evaluate.py`` scores against self-distilled references (the base model's own
translation of an expanded phrase), so chrF is inflated and the base model's mistakes
count as correct. This module scores against references a human wrote and checked.

Gold row (one JSON object per line of ``data/gold/gold.jsonl``)::

    {"id": "g001", "src": "wts 2 potions pm me", "lang": "ru",
     "ref": "...hand-checked translation...",
     "category": "abbr",                       # abbr | keep | ordinary | mixed | ocr_noise
     "keep_terms": ["pm"],                     # optional: terms that must survive verbatim
     "wrong_expansions": ["личное сообщение"], # optional: substrings that count as a wrong expansion
     "noisy_src": "wts 2 p0tions pm rne"}      # optional: the same line as OCR would misread it

Privacy: gold lines must be anonymised (no nicknames, no real screen text of a third
party). The file lives under ``data/`` (DVC-tracked, never in git) and is never used
for training; ``check_no_leak`` enforces that.

Scores per category: chrF, keep-rate, wrong-expansion rate; OCR robustness = clean minus
noisy chrF on rows with ``noisy_src``. ``aggregate`` combines the summaries of several
training seeds into mean / std / 95 % CI.

Usage
-----
    python training/gold_eval.py validate data/gold/gold.jsonl --train data/processed_v2/train.jsonl
    python training/gold_eval.py score data/gold/gold.jsonl \\
        v0-base=ct2:models/nllb-v0-base v2-game=ct2:models/nllb-v2-game --out checkpoints/gold
    python training/gold_eval.py noise data/gold/gold.jsonl --out data/gold/gold_noisy.jsonl
    python training/gold_eval.py aggregate checkpoints/gold_s1.json checkpoints/gold_s2.json checkpoints/gold_s3.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import evaluate  # training/evaluate.py: the script directory is on sys.path
import tracking

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_JSONL = _PROJECT_ROOT / "data" / "gold" / "gold.jsonl"
GOLD_OUT_DIR = _PROJECT_ROOT / "checkpoints" / "gold"

CATEGORIES = ("abbr", "keep", "ordinary", "mixed", "ocr_noise")
# ISO 639-1 → FLORES-200 target codes of the languages the app is evaluated on
TGT_CODES = {"ru": "rus_Cyrl", "uk": "ukr_Cyrl", "pl": "pol_Latn", "de": "deu_Latn", "es": "spa_Latn", "fr": "fra_Latn"}
MIN_RECOMMENDED_ROWS = 300

# two-sided 95 % Student t critical values by degrees of freedom; 1.96 beyond the table
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


# ── loading and validation ────────────────────────────────────────────────


def validate_rows(rows: list[dict]) -> list[str]:
    """Return human-readable problems of a gold set (empty list = valid)."""
    problems: list[str] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, 1):
        where = f"row {n} ({row.get('id', '?')})"
        for key in ("id", "src", "lang", "ref", "category"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                problems.append(f"{where}: '{key}' must be a non-empty string")
        if row.get("id") in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(row.get("id", ""))
        if row.get("category") not in CATEGORIES:
            problems.append(f"{where}: category must be one of {', '.join(CATEGORIES)}")
        if row.get("lang") not in TGT_CODES:
            problems.append(f"{where}: unsupported lang {row.get('lang')!r}")
        for key in ("keep_terms", "wrong_expansions"):
            value = row.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                problems.append(f"{where}: '{key}' must be a list of non-empty strings")
        if "noisy_src" in row and (not isinstance(row["noisy_src"], str) or not row["noisy_src"].strip()):
            problems.append(f"{where}: 'noisy_src' must be a non-empty string")
        if row.get("noisy_src") == row.get("src"):
            problems.append(f"{where}: 'noisy_src' equals 'src' (not a distortion)")
    return problems


def load_gold(path: Path = GOLD_JSONL) -> list[dict]:
    """Read and validate a gold set; raise ``ValueError`` listing every problem."""
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: invalid JSON ({exc.msg})") from exc
    problems = validate_rows(rows)
    if problems:
        raise ValueError("invalid gold set:\n  " + "\n  ".join(problems))
    return rows


def gold_hash(path: Path = GOLD_JSONL) -> str:
    """SHA-256 of the gold file, stored in every summary so a score names its exact test set."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_no_leak(gold: list[dict], train_rows: list[dict]) -> list[str]:
    """Gold sources (clean or noisy) that also occur as a training source. Must be empty."""
    train_sources = {_norm(r["src"]) for r in train_rows if "src" in r}
    leaked = []
    for row in gold:
        for key in ("src", "noisy_src"):
            if key in row and _norm(row[key]) in train_sources:
                leaked.append(f"{row['id']}: {key} is in the training set")
    return leaked


def category_counts(rows: list[dict]) -> dict[str, int]:
    counts = {c: 0 for c in CATEGORIES}
    for row in rows:
        counts[row["category"]] += 1
    return counts


# ── scoring ───────────────────────────────────────────────────────────────


def to_eval_rows(rows: list[dict], *, noisy: bool = False) -> list[dict]:
    """Rows in the shape ``evaluate.translate_ct2`` / ``translate_hf`` expect."""
    return [
        {"src": r["noisy_src"] if noisy else r["src"], "tgt": r["ref"], "tgt_code": TGT_CODES[r["lang"]]} for r in rows
    ]


def has_wrong_expansion(hyp: str, forbidden: list[str]) -> bool:
    low = hyp.lower()
    return any(f.lower() in low for f in forbidden)


def _chrf(hyps: list[str], refs: list[str]) -> float:
    from sacrebleu.metrics import CHRF

    return round(CHRF().corpus_score(hyps, [refs]).score, 2)


def score_gold(rows: list[dict], hyps: list[str], noisy_hyps: dict[int, str] | None = None) -> dict:
    """Scores of one system on a gold set.

    ``hyps[i]`` translates ``rows[i]["src"]``; ``noisy_hyps[i]`` translates its ``noisy_src``
    (only rows that have one). Categories with no rows are omitted.
    """
    by_cat: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        by_cat[row["category"]].append(i)

    def refs(idx):
        return [rows[i]["ref"] for i in idx]

    def hs(idx):
        return [hyps[i] for i in idx]

    keep_idx = [i for i, r in enumerate(rows) if r.get("keep_terms")]
    exp_idx = [i for i, r in enumerate(rows) if r.get("wrong_expansions")]
    result: dict = {
        "rows": len(rows),
        "chrf": _chrf(hs(range(len(rows))), refs(range(len(rows)))) if rows else None,
        "chrf_by_category": {c: _chrf(hs(idx), refs(idx)) for c, idx in by_cat.items()},
        "chrf_by_lang": {},
        "keep_rate": None,
        "wrong_expansion_rate": None,
        "ocr_noise": None,
    }
    for lang in sorted({r["lang"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["lang"] == lang]
        result["chrf_by_lang"][lang] = _chrf(hs(idx), refs(idx))
    if keep_idx:
        ok = sum(evaluate.keep_ok(hyps[i], rows[i]["keep_terms"]) for i in keep_idx)
        result["keep_rate"] = round(100 * ok / len(keep_idx), 1)
    if exp_idx:
        bad = sum(has_wrong_expansion(hyps[i], rows[i]["wrong_expansions"]) for i in exp_idx)
        result["wrong_expansion_rate"] = round(100 * bad / len(exp_idx), 1)
    if noisy_hyps:
        idx = sorted(noisy_hyps)
        clean = _chrf(hs(idx), refs(idx))
        noisy = _chrf([noisy_hyps[i] for i in idx], refs(idx))
        result["ocr_noise"] = {
            "rows": len(idx),
            "chrf_clean": clean,
            "chrf_noisy": noisy,
            "drop": round(clean - noisy, 2),
        }
    return result


# ── several seeds → mean / std / CI ───────────────────────────────────────


def mean_ci(values: list[float]) -> dict:
    """Mean, sample std and 95 % CI half-width of one metric over training seeds."""
    n = len(values)
    if n == 0:
        raise ValueError("no values")
    mean = statistics.fmean(values)
    if n == 1:
        return {"n": 1, "mean": round(mean, 2), "std": 0.0, "ci95": None}
    std = statistics.stdev(values)
    t = _T95.get(n - 1, 1.96)
    return {"n": n, "mean": round(mean, 2), "std": round(std, 2), "ci95": round(t * std / math.sqrt(n), 2)}


def _flatten(score: dict) -> dict[str, float]:
    flat: dict[str, float] = {}
    for key in ("chrf", "keep_rate", "wrong_expansion_rate"):
        if score.get(key) is not None:
            flat[key] = score[key]
    for cat, value in score.get("chrf_by_category", {}).items():
        flat[f"chrf[{cat}]"] = value
    for lang, value in score.get("chrf_by_lang", {}).items():
        flat[f"chrf[{lang}]"] = value
    if score.get("ocr_noise"):
        flat["ocr_noise_drop"] = score["ocr_noise"]["drop"]
    return flat


def aggregate(scores: list[dict]) -> dict[str, dict]:
    """Combine ``score_gold`` results of the same system trained with different seeds."""
    columns: dict[str, list[float]] = defaultdict(list)
    for score in scores:
        for key, value in _flatten(score).items():
            columns[key].append(value)
    return {key: mean_ci(values) for key, values in sorted(columns.items())}


# ── OCR-noise generation ──────────────────────────────────────────────────

# typical EasyOCR confusions on game-chat fonts: (clean, misread)
_OCR_CONFUSIONS = [
    ("l", "I"),
    ("I", "l"),
    ("o", "0"),
    ("O", "0"),
    ("m", "rn"),
    ("rn", "m"),
    ("e", "c"),
    ("i", "1"),
    ("a", "o"),
]


def add_ocr_noise(text: str, rng: random.Random, rate: float = 0.08) -> str:
    """Distort ``text`` the way OCR would: look-alike swaps, a stray or lost space.

    Deterministic for a given ``rng`` state. Always returns a string different from the
    input when at least one confusable character exists; otherwise inserts a stray space.
    """
    out = list(text)
    spots = [i for i, ch in enumerate(out) if any(ch == a for a, _ in _OCR_CONFUSIONS if len(a) == 1)]
    rng.shuffle(spots)
    changed = 0
    for i in spots:
        if changed and rng.random() > rate * 4:
            continue
        options = [b for a, b in _OCR_CONFUSIONS if a == out[i]]
        out[i] = rng.choice(options)
        changed += 1
        if changed >= 3:
            break
    noisy = "".join(out)
    if noisy == text and len(text) > 2:
        pos = rng.randrange(1, len(text) - 1)
        noisy = text[:pos] + " " + text[pos:]
    return noisy


def fill_noisy_src(rows: list[dict], seed: int = 0) -> int:
    """Add ``noisy_src`` to rows lacking it (in place); returns the number of rows changed."""
    rng = random.Random(seed)
    n = 0
    for row in rows:
        if "noisy_src" in row:
            continue
        noisy = add_ocr_noise(row["src"], rng)
        if noisy != row["src"]:
            row["noisy_src"] = noisy
            n += 1
    return n


# ── CLI ───────────────────────────────────────────────────────────────────


def _cmd_validate(args) -> int:
    try:
        rows = load_gold(args.gold)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    counts = category_counts(rows)
    print(f"{len(rows)} rows, sha256 {gold_hash(args.gold)[:12]}")
    print("categories:", ", ".join(f"{c}={n}" for c, n in counts.items()))
    if len(rows) < MIN_RECOMMENDED_ROWS:
        print(f"warning: fewer than {MIN_RECOMMENDED_ROWS} rows — scores will be noisy", file=sys.stderr)
    status = 0
    for train in args.train:
        train_rows = [json.loads(l) for l in Path(train).read_text(encoding="utf-8").splitlines() if l.strip()]
        leaked = check_no_leak(rows, train_rows)
        for line in leaked:
            print(f"LEAK vs {train}: {line}", file=sys.stderr)
        status = status or (1 if leaked else 0)
    return status


def _translate(spec_kind: str, path: str, rows: list[dict], batch_size: int) -> list[str]:
    if spec_kind == "ct2":
        return evaluate.translate_ct2(Path(path), rows, batch_size)
    if spec_kind == "hf":
        return evaluate.translate_hf(Path(path), None, rows, batch_size)
    if spec_kind == "lora":
        base, _, adapter = path.partition("+")
        return evaluate.translate_hf(Path(base), Path(adapter), rows, batch_size)
    raise ValueError(f"unknown system type: {spec_kind}")


def _cmd_score(args) -> int:
    rows = load_gold(args.gold)
    out_dir = args.out if args.out.is_absolute() else _PROJECT_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    noisy_idx = [i for i, r in enumerate(rows) if "noisy_src" in r]
    summary = {"gold": str(args.gold), "gold_sha256": gold_hash(args.gold), "rows": len(rows), "systems": {}}
    for spec in args.systems:
        name, _, target = spec.partition("=")
        kind, _, path = target.partition(":")
        hyps = _translate(kind, path, to_eval_rows(rows), args.batch_size)
        noisy = {}
        if noisy_idx:
            noisy_rows = to_eval_rows([rows[i] for i in noisy_idx], noisy=True)
            noisy = dict(zip(noisy_idx, _translate(kind, path, noisy_rows, args.batch_size)))
        summary["systems"][name] = {"spec": spec, **score_gold(rows, hyps, noisy)}
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for i, (row, hyp) in enumerate(zip(rows, hyps)):
                f.write(json.dumps({"id": row["id"], "hyp": hyp, "noisy_hyp": noisy.get(i)}, ensure_ascii=False) + "\n")
        print(f"[{name}] chrF {summary['systems'][name]['chrf']}", flush=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, result in summary["systems"].items():
        tracking.log_run(
            "gold-eval",
            name,
            params={"spec": result["spec"], "rows": len(rows)},
            metrics={k: v for k, v in result.items() if k not in {"spec", "rows"}},
            tags={"gold_sha256": summary["gold_sha256"]},
            artifacts=[out_dir / "summary.json"],
        )
    return 0


def _cmd_noise(args) -> int:
    try:
        rows = load_gold(args.gold)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    n = fill_noisy_src(rows, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"added noisy_src to {n} rows -> {args.out}")
    return 0


def _cmd_aggregate(args) -> int:
    summaries = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.summaries]
    hashes = {s.get("gold_sha256") for s in summaries}
    if len(hashes) != 1:
        print("summaries were scored on different gold sets", file=sys.stderr)
        return 1
    names = set.intersection(*(set(s["systems"]) for s in summaries))
    if not names:
        print("no system appears in every summary", file=sys.stderr)
        return 1
    result = {name: aggregate([s["systems"][name] for s in summaries]) for name in sorted(names)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score NLLB systems on the hand-checked gold set.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="check the schema, print counts and look for training leakage")
    p.add_argument("gold", type=Path, nargs="?", default=GOLD_JSONL)
    p.add_argument("--train", type=Path, action="append", default=[], help="training jsonl to check for leakage")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("score", help="translate the gold set with each system and score it")
    p.add_argument("gold", type=Path)
    p.add_argument("systems", nargs="+", help="name=ct2:<dir> | name=hf:<dir> | name=lora:<base>+<adapter>")
    p.add_argument("--out", type=Path, default=GOLD_OUT_DIR)
    p.add_argument("--batch-size", type=int, default=16)
    p.set_defaults(func=_cmd_score)

    p = sub.add_parser("noise", help="add synthetic OCR-style noisy_src to rows that lack one")
    p.add_argument("gold", type=Path)
    p.add_argument("--out", type=Path, required=True, help="output jsonl (the input is never overwritten)")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=_cmd_noise)

    p = sub.add_parser("aggregate", help="mean / std / 95 %% CI over summaries of different training seeds")
    p.add_argument("summaries", nargs="+", type=Path)
    p.set_defaults(func=_cmd_aggregate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
