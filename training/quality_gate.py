"""
training/quality_gate.py — the quality gate a candidate model build must pass (roadmap stage 7).

Input is a ``gold_eval.py score`` summary that holds both the candidate and the current stable
system, so the two are scored on the same gold set by the same code. The gate compares them with
the thresholds in ``configs/quality_gate.json`` and exits 0 only if every check passes:

  * rows              the gold set has at least ``min_rows`` lines;
  * keep rate         candidate keep rate >= ``min_keep_rate``;
  * overall chrF      candidate may lose at most ``max_chrf_drop`` points against the baseline;
  * ordinary words    chrF on the ``ordinary`` category may drop at most ``max_ordinary_chrf_drop``;
  * wrong expansion   candidate wrong-expansion rate <= ``max_wrong_expansion_rate``;
  * OCR noise         the chrF lost on noisy input may grow at most ``max_ocr_drop_increase``.

A metric that is missing (for example no ``ocr_noise`` rows) FAILS its check: a gate that cannot
measure something must not wave the build through. Fix the thresholds before looking at results.

Usage
-----
    python training/quality_gate.py checkpoints/gold/summary.json --candidate v3 --baseline v2-game \\
        --report checkpoints/gold/gate.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLDS = _PROJECT_ROOT / "configs" / "quality_gate.json"
REQUIRED_KEYS = (
    "min_rows",
    "min_keep_rate",
    "max_chrf_drop",
    "max_ordinary_chrf_drop",
    "max_wrong_expansion_rate",
    "max_ocr_drop_increase",
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if not isinstance(data.get(k), (int, float))]
    if missing:
        raise ValueError(f"thresholds lack numeric values for: {', '.join(missing)}")
    return data


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _metrics(system: dict) -> dict:
    ocr = system.get("ocr_noise") or {}
    return {
        "chrf": _num(system.get("chrf")),
        "keep_rate": _num(system.get("keep_rate")),
        "wrong_expansion_rate": _num(system.get("wrong_expansion_rate")),
        "ordinary": _num((system.get("chrf_by_category") or {}).get("ordinary")),
        "ocr_drop": _num(ocr.get("drop")),
        "rows": _num(system.get("rows")),
    }


def evaluate_gate(candidate: dict, baseline: dict, thresholds: dict) -> list[Check]:
    """Run every check on two ``score_gold`` results."""
    cand, base = _metrics(candidate), _metrics(baseline)
    checks: list[Check] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(Check(name, passed, detail))

    def need(name: str, *values) -> bool:
        if any(v is None for v in values):
            add(name, False, "metric missing in the summary")
            return False
        return True

    if need("rows", cand["rows"]):
        add(
            "rows", cand["rows"] >= thresholds["min_rows"], f"{cand['rows']:.0f} rows, need >= {thresholds['min_rows']}"
        )
    if need("keep rate", cand["keep_rate"]):
        add(
            "keep rate",
            cand["keep_rate"] >= thresholds["min_keep_rate"],
            f"{cand['keep_rate']:.1f} %, need >= {thresholds['min_keep_rate']}",
        )
    if need("overall chrF", cand["chrf"], base["chrf"]):
        drop = base["chrf"] - cand["chrf"]
        add(
            "overall chrF",
            drop <= thresholds["max_chrf_drop"],
            f"{cand['chrf']:.2f} vs {base['chrf']:.2f} (drop {drop:+.2f}, allowed {thresholds['max_chrf_drop']})",
        )
    if need("ordinary-word chrF", cand["ordinary"], base["ordinary"]):
        drop = base["ordinary"] - cand["ordinary"]
        add(
            "ordinary-word chrF",
            drop <= thresholds["max_ordinary_chrf_drop"],
            f"{cand['ordinary']:.2f} vs {base['ordinary']:.2f} (drop {drop:+.2f}, allowed {thresholds['max_ordinary_chrf_drop']})",
        )
    if need("wrong expansions", cand["wrong_expansion_rate"]):
        add(
            "wrong expansions",
            cand["wrong_expansion_rate"] <= thresholds["max_wrong_expansion_rate"],
            f"{cand['wrong_expansion_rate']:.1f} %, allowed <= {thresholds['max_wrong_expansion_rate']}",
        )
    if need("OCR noise", cand["ocr_drop"], base["ocr_drop"]):
        grow = cand["ocr_drop"] - base["ocr_drop"]
        add(
            "OCR noise",
            grow <= thresholds["max_ocr_drop_increase"],
            f"noise costs {cand['ocr_drop']:.2f} vs {base['ocr_drop']:.2f} chrF (growth {grow:+.2f}, allowed {thresholds['max_ocr_drop_increase']})",
        )
    return checks


def passed(checks: list[Check]) -> bool:
    return bool(checks) and all(c.passed for c in checks)


def render_report(checks: list[Check], candidate: str, baseline: str, gold_sha256: str | None = None) -> str:
    verdict = "PASSED" if passed(checks) else "FAILED"
    lines = [f"## Quality gate: {candidate} vs {baseline} — {verdict}", ""]
    if gold_sha256:
        lines += [f"Gold set SHA-256: `{gold_sha256}`", ""]
    lines += ["| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c.name} | {'pass' if c.passed else '**FAIL**'} | {c.detail} |" for c in checks]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quality gate for a candidate NLLB build.")
    parser.add_argument("summary", type=Path, help="summary.json written by gold_eval.py score")
    parser.add_argument("--candidate", required=True, help="system name of the candidate in the summary")
    parser.add_argument("--baseline", required=True, help="system name of the current stable build")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--report", type=Path, help="write the Markdown report here")
    args = parser.parse_args(argv)

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    systems = summary.get("systems", {})
    for name in (args.candidate, args.baseline):
        if name not in systems:
            print(f"system {name!r} is not in {args.summary} (has: {', '.join(systems) or 'none'})", file=sys.stderr)
            return 2
    checks = evaluate_gate(systems[args.candidate], systems[args.baseline], load_thresholds(args.thresholds))
    report = render_report(checks, args.candidate, args.baseline, summary.get("gold_sha256"))
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    return 0 if passed(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
