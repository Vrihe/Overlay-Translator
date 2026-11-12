"""
scripts/monitor_report.py — roadmap stage 10a: monitor the local model from the app's history.

Reads the translation history (the SQLite ``translations`` table, opened read-only) and reports,
for the offline model's rows (``domain_id`` ending in ``|nllb``):

* the share of source lines with an *unknown token*: a slang-looking word that is not in the
  game glossary (``translate/glossary/game_en.json``);
* the top-N *lost keep terms*: glossary terms that must stay verbatim, present in the source
  but missing from the translation;
* a drift signal: the unknown-token share of the recent window against the earlier rows.

"Unknown" is a heuristic that needs no dictionary: a letter/digit mix (``lf2m``) or a short
vowelless word (``wtb``, ``pls``) outside the glossary. Pass ``--vocab`` (one word per line) to
mark ordinary words as known and cut false positives.

Privacy: the history is user data. The report prints counts and glossary terms only; the unknown
tokens themselves are shown only with ``--show-tokens`` (they are fragments of screen text).
Latency is not in the history table, so it is not reported here.

Usage
-----
    python scripts/monitor_report.py
    python scripts/monitor_report.py --db path/to/translations.db --window-days 14 --top 15 --json report.json

Exit code 2 means drift was detected ("time to update the glossary / retrain"), 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_history_dataset as history  # noqa: E402

GLOSSARY_PATH = _PROJECT_ROOT / "translate" / "glossary" / "game_en.json"
NLLB_SUFFIX = history.NLLB_DOMAIN_SUFFIX
MIN_ROWS_FOR_DRIFT = 50
DEFAULT_DRIFT_POINTS = 5.0  # percentage points of unknown-token share

_TOKEN = re.compile(r"[A-Za-z0-9+']+")
_VOWELS = set("aeiouyAEIOUY")


def load_glossary(path: Path = GLOSSARY_PATH) -> tuple[set[str], set[str]]:
    """Return ``(all terms, keep terms)``, lower-cased. A term mapped to ``null`` is a keep term."""
    terms = json.loads(path.read_text(encoding="utf-8"))["terms"]
    known = {t.lower() for t in terms}
    keep = {t.lower() for t, expansion in terms.items() if expansion is None}
    return known, keep


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def is_unknown(token: str, glossary: set[str], vocab: set[str] | None = None) -> bool:
    """A slang-looking token that neither the glossary nor the optional vocabulary knows."""
    if token in glossary or (vocab is not None and token in vocab):
        return False
    letters = [c for c in token if c.isalpha()]
    if not letters or len(token) < 2:
        return False
    has_digit = any(c.isdigit() for c in token)
    if has_digit and letters:
        return True  # a letter/digit mix like lf2m; known forms are already in the glossary
    return len(token) <= 5 and not any(c in _VOWELS for c in token)


def unknown_tokens(text: str, glossary: set[str], vocab: set[str] | None = None) -> list[str]:
    return [t for t in tokens(text) if is_unknown(t, glossary, vocab)]


def lost_keep_terms(source: str, translation: str, keep: set[str]) -> list[str]:
    """Keep terms found in *source* but absent from *translation* (whole-word, case-insensitive)."""
    lost = []
    for term in keep:
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        if re.search(pattern, source, re.IGNORECASE) and not re.search(pattern, translation, re.IGNORECASE):
            lost.append(term)
    return lost


def share(rows: list[dict], glossary: set[str], vocab: set[str] | None = None) -> tuple[float, int]:
    """Percentage of rows with at least one unknown token, and the row count."""
    if not rows:
        return 0.0, 0
    hit = sum(1 for r in rows if unknown_tokens(r["source_text"], glossary, vocab))
    return 100.0 * hit / len(rows), len(rows)


def drift(
    rows: list[dict],
    glossary: set[str],
    *,
    now: float,
    window_days: float,
    threshold: float = DEFAULT_DRIFT_POINTS,
    vocab: set[str] | None = None,
) -> dict:
    """Compare the unknown-token share of the last *window_days* with the earlier rows."""
    cutoff = now - window_days * 86400
    recent = [r for r in rows if r["timestamp"] >= cutoff]
    earlier = [r for r in rows if r["timestamp"] < cutoff]
    recent_share, n_recent = share(recent, glossary, vocab)
    earlier_share, n_earlier = share(earlier, glossary, vocab)
    enough = n_recent >= MIN_ROWS_FOR_DRIFT and n_earlier >= MIN_ROWS_FOR_DRIFT
    delta = round(recent_share - earlier_share, 2)
    return {
        "recent_share": round(recent_share, 2),
        "earlier_share": round(earlier_share, 2),
        "recent_rows": n_recent,
        "earlier_rows": n_earlier,
        "delta_points": delta,
        "enough_data": enough,
        "drift": bool(enough and delta > threshold),
    }


def build_report(
    rows: list[dict],
    glossary: set[str],
    keep: set[str],
    *,
    now: float,
    window_days: float = 30,
    top: int = 10,
    threshold: float = DEFAULT_DRIFT_POINTS,
    vocab: set[str] | None = None,
    show_tokens: bool = False,
) -> dict:
    """Report over the offline model's rows (``domain_id`` ending in ``|nllb``)."""
    nllb = [r for r in rows if str(r.get("domain_id", "")).endswith(NLLB_SUFFIX)]
    unknown_share, n = share(nllb, glossary, vocab)
    lost = Counter()
    unknown = Counter()
    for r in nllb:
        lost.update(lost_keep_terms(r["source_text"], r["translated_text"], keep))
        if show_tokens:
            unknown.update(unknown_tokens(r["source_text"], glossary, vocab))
    report = {
        "rows": n,
        "unknown_token_share": round(unknown_share, 2),
        "lost_keep_terms": lost.most_common(top),
        "drift": drift(nllb, glossary, now=now, window_days=window_days, threshold=threshold, vocab=vocab),
    }
    if show_tokens:
        report["top_unknown_tokens"] = unknown.most_common(top)
    return report


def format_report(report: dict) -> str:
    d = report["drift"]
    lines = [
        f"Offline-model rows: {report['rows']}",
        f"Rows with an unknown token: {report['unknown_token_share']} %",
        "Top lost keep terms: " + (", ".join(f"{t} ({c})" for t, c in report["lost_keep_terms"]) or "none"),
    ]
    if "top_unknown_tokens" in report:
        lines.append("Top unknown tokens: " + ", ".join(f"{t} ({c})" for t, c in report["top_unknown_tokens"]))
    lines.append(
        f"Drift: recent {d['recent_share']} % ({d['recent_rows']} rows) vs earlier {d['earlier_share']} % "
        f"({d['earlier_rows']} rows), {d['delta_points']:+} points"
    )
    if not d["enough_data"]:
        lines.append(f"Not enough rows for a drift verdict (need {MIN_ROWS_FOR_DRIFT} in each period).")
    elif d["drift"]:
        lines.append("DRIFT: unknown tokens are growing - update the glossary or retrain (docs/training.md).")
    else:
        lines.append("No drift.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor the offline model from the translation history.")
    parser.add_argument("--db", type=Path, default=None, help="path to translations.db (default: app user-data dir)")
    parser.add_argument("--glossary", type=Path, default=GLOSSARY_PATH)
    parser.add_argument("--vocab", type=Path, help="word list (one per line) of ordinary words to treat as known")
    parser.add_argument("--window-days", type=float, default=30)
    parser.add_argument("--threshold", type=float, default=DEFAULT_DRIFT_POINTS, help="drift threshold, points")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--show-tokens", action="store_true", help="also list the top unknown tokens (screen text)")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args(argv)

    db_path = args.db or history.default_db_path()
    if not db_path.is_file():
        print(f"history database not found: {db_path}", file=sys.stderr)
        return 1
    glossary, keep = load_glossary(args.glossary)
    vocab = None
    if args.vocab:
        vocab = {w.strip().lower() for w in args.vocab.read_text(encoding="utf-8").splitlines() if w.strip()}
    report = build_report(
        history.load_rows(db_path),
        glossary,
        keep,
        now=time.time(),
        window_days=args.window_days,
        top=args.top,
        threshold=args.threshold,
        vocab=vocab,
        show_tokens=args.show_tokens,
    )
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 2 if report["drift"]["drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
