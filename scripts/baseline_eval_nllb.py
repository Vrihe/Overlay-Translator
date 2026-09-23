"""
scripts/baseline_eval_nllb.py — baseline quality of un-tuned NLLB on real history.

Takes pairs exported by ``scripts/export_history_dataset.py`` (i.e. real captured
text with the API translation as reference), runs the quantized CTranslate2 NLLB
over the sources, and scores the hypotheses against the references with chrF.

This is the "before" number: rerun it after fine-tuning and compare.

The reference side is an LLM translation, not a human one, so chrF here measures
*agreement with the current API backend*, not absolute quality. Treat the score
as a relative baseline and read the printed side-by-side samples too.

Usage
-----
    python scripts/baseline_eval_nllb.py
    python scripts/baseline_eval_nllb.py --sample 30 --out docs/baseline_eval.md
    python scripts/baseline_eval_nllb.py --dataset data/history_pairs.jsonl --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_dataset(path: Path) -> list[dict]:
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[warn] {path}:{line_no} is not valid JSON ({exc}) — skipped",
                      file=sys.stderr)
    return records


def chrf_scorer():
    """Return (corpus_fn, sentence_fn, backend_name)."""
    import sacrebleu
    from sacrebleu.metrics import CHRF

    metric = CHRF()  # char_order=6, word_order=0, beta=2 — sacrebleu defaults

    def corpus(hyps: list[str], refs: list[str]) -> float:
        return metric.corpus_score(hyps, [refs]).score

    def sentence(hyp: str, ref: str) -> float:
        return metric.sentence_score(hyp, [ref]).score

    return corpus, sentence, f"chrF (sacrebleu {sacrebleu.__version__}, beta=2, char_order=6)"


def truncate(text: str, limit: int = 220) -> str:
    flat = " ⏎ ".join(text.splitlines())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path,
                        default=_PROJECT_ROOT / "data" / "history_pairs.jsonl")
    parser.add_argument("--out", type=Path, default=_PROJECT_ROOT / "docs" / "baseline_eval.md")
    parser.add_argument("--sample", type=int, default=30,
                        help="how many random pairs to evaluate (default: 30)")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--model", type=Path, default=None,
                        help="CTranslate2 model dir (default: the app's auto-discovery)")
    parser.add_argument("--max-source-chars", type=int, default=1500,
                        help="skip pathologically long OCR dumps (default: 1500)")
    args = parser.parse_args()

    if not args.dataset.is_file():
        print(f"[FAIL] Dataset not found: {args.dataset}\n"
              f"Run scripts/export_history_dataset.py first.", file=sys.stderr)
        return 1

    records = load_dataset(args.dataset)
    usable = [r for r in records
              if r.get("source") and r.get("target")
              and len(r["source"]) <= args.max_source_chars]
    skipped_long = len(records) - len(usable)

    if not usable:
        print("[FAIL] No usable pairs in the dataset.", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    sample = usable if len(usable) <= args.sample else rng.sample(usable, args.sample)

    from translate.nllb_backend import NllbBackend, resolve_model_dir

    model_dir = args.model or resolve_model_dir()
    if model_dir is None:
        print("[FAIL] Local NLLB model not found. Convert it first "
              "(see scripts/test_nllb_translation.py).", file=sys.stderr)
        return 1

    backend = NllbBackend(model_dir)
    backend.ensure_loaded()

    corpus_chrf, sentence_chrf, metric_name = chrf_scorer()

    rows: list[dict] = []
    latencies: list[float] = []
    failures: list[tuple[dict, str]] = []

    for record in sample:
        src_lang = record.get("src_lang", "")
        tgt_lang = record.get("tgt_lang", "")
        t0 = time.perf_counter()
        try:
            hypothesis = backend._raw_translate(
                record["source"],
                backend._flores(src_lang),
                backend._flores(tgt_lang),
            )
        except Exception as exc:
            failures.append((record, str(exc)))
            continue
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)

        rows.append({
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "source": record["source"],
            "reference": record["target"],
            "hypothesis": hypothesis,
            "chrf": sentence_chrf(hypothesis, record["target"]),
            "seconds": elapsed,
        })

    if not rows:
        print("[FAIL] Every pair failed to translate.", file=sys.stderr)
        for record, err in failures:
            print(f"  {record.get('src_lang')}->{record.get('tgt_lang')}: {err}", file=sys.stderr)
        return 1

    overall = corpus_chrf([r["hypothesis"] for r in rows], [r["reference"] for r in rows])
    sentence_scores = [r["chrf"] for r in rows]

    # ── Console report ───────────────────────────────────
    print(f"Dataset      : {args.dataset}  ({len(records)} pairs, {len(usable)} usable)")
    print(f"Evaluated    : {len(rows)} pairs (seed={args.seed})")
    print(f"Model        : {model_dir}")
    print(f"Metric       : {metric_name}")
    print("-" * 78)
    print(f"Corpus chrF  : {overall:.2f}")
    print(f"Sentence chrF: mean {statistics.fmean(sentence_scores):.2f} | "
          f"median {statistics.median(sentence_scores):.2f} | "
          f"min {min(sentence_scores):.2f} | max {max(sentence_scores):.2f}")
    print(f"Latency      : mean {statistics.fmean(latencies) * 1000:.0f} ms | "
          f"max {max(latencies) * 1000:.0f} ms")
    if failures:
        print(f"Failures     : {len(failures)}")
    print("-" * 78)
    for row in sorted(rows, key=lambda r: r["chrf"], reverse=True):
        print(f"[{row['src_lang']}->{row['tgt_lang']}] chrF {row['chrf']:5.1f}")
        print(f"    src : {truncate(row['source'])}")
        print(f"    ref : {truncate(row['reference'])}")
        print(f"    nllb: {truncate(row['hypothesis'])}")

    # ── Markdown report ──────────────────────────────────
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Baseline: NLLB-200-distilled-600M (int8, no fine-tuning)\n")
    lines.append("Reference point for comparison after fine-tuning. "
                 "Re-run this same script with the same `--seed` after fine-tuning.\n")
    lines.append("## Setup\n")
    lines.append(f"| Parameter | Value |\n|---|---|")
    lines.append(f"| Run date | {date.today().isoformat()} |")
    lines.append(f"| Model | `{model_dir}` |")
    lines.append(f"| Quantization | int8, CTranslate2, CPU |")
    lines.append(f"| Dataset | `{args.dataset.relative_to(_PROJECT_ROOT) if args.dataset.is_relative_to(_PROJECT_ROOT) else args.dataset}` |")
    lines.append(f"| Pairs in dataset | {len(records)} (usable: {len(usable)}"
                 + (f", dropped as too long: {skipped_long}" if skipped_long else "") + ") |")
    lines.append(f"| Pairs evaluated | {len(rows)} |")
    lines.append(f"| Sampling seed | {args.seed} |")
    lines.append(f"| Metric | {metric_name} |")
    lines.append("")
    lines.append("> The reference (`ref`) is the translation produced by the API backend and saved in "
                 "history, not a human translation. So chrF measures **agreement with the current "
                 "API backend**, not absolute quality. The number is only meaningful when compared "
                 "with an identical run after fine-tuning.\n")
    if len(rows) < args.sample:
        lines.append("## ⚠ Sample size limitation\n")
        lines.append(
            f"Only **{len(rows)}** pairs were evaluated instead of the requested {args.sample}: "
            "that is all the translation history contains. On a sample this small chrF is not "
            "statistically significant: a single sentence moves the corpus score by tens of points.\n"
        )
        lines.append(
            "For the baseline to be meaningful, accumulate real history "
            "(use the app with the API backend), then re-run:\n"
        )
        lines.append("```bash")
        lines.append("python scripts/export_history_dataset.py")
        lines.append(f"python scripts/baseline_eval_nllb.py --seed {args.seed}")
        lines.append("```\n")
        lines.append(
            "Until then, rely on the \"Examples for manual review\" section "
            "and on `scripts/test_nllb_translation.py`, whose phrases are chosen "
            "for the target domain (game chat).\n"
        )

    lines.append("## Results\n")
    lines.append("| Metric | Value |\n|---|---|")
    lines.append(f"| **Corpus chrF** | **{overall:.2f}** |")
    lines.append(f"| Sentence chrF, mean | {statistics.fmean(sentence_scores):.2f} |")
    lines.append(f"| Sentence chrF, median | {statistics.median(sentence_scores):.2f} |")
    lines.append(f"| Sentence chrF, min / max | {min(sentence_scores):.2f} / {max(sentence_scores):.2f} |")
    lines.append(f"| Inference time, mean | {statistics.fmean(latencies) * 1000:.0f} ms |")
    lines.append(f"| Inference time, max | {max(latencies) * 1000:.0f} ms |")
    if failures:
        lines.append(f"| Translation errors | {len(failures)} |")
    lines.append("")
    lines.append("## Examples for manual review\n")
    lines.append("Sorted by chrF, descending.\n")
    for row in sorted(rows, key=lambda r: r["chrf"], reverse=True):
        lines.append(f"### `{row['src_lang']} → {row['tgt_lang']}` · chrF {row['chrf']:.1f}\n")
        lines.append(f"- **Source:** `{truncate(row['source'], 400)}`")
        lines.append(f"- **Reference (API):** `{truncate(row['reference'], 400)}`")
        lines.append(f"- **NLLB baseline:** `{truncate(row['hypothesis'], 400)}`\n")
    if failures:
        lines.append("## Failed pairs\n")
        for record, err in failures:
            lines.append(f"- `{record.get('src_lang')} → {record.get('tgt_lang')}`: {err}")
        lines.append("")
    lines.append("---\n")
    lines.append("_Generated by `scripts/baseline_eval_nllb.py`._\n")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("-" * 78)
    print(f"Report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
