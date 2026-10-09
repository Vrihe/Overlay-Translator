"""
training/prepare_abbreviations.py — stage 1 of the NLLB fine-tune: clean the
abbreviation list.

Reads ``data/raw/txt-sms-abbreviations/sms.csv`` (willwade/txt-sms-abbreviations,
Apache-2.0) and drops:
  * rows whose abbreviation is already a regular word (``IsWord`` == True);
  * rows with no letters at all (numbers such as ``143`` or ``.02``);
  * duplicate abbreviations (case-insensitive, first expansion wins).

The dataset has no usage counts, so the rows are ranked by the Zipf frequency
of the abbreviation in ``wordfreq``'s English corpus (web, Twitter, Reddit,
subtitles). Abbreviations that wordfreq splits into several tokens (``*S*``,
``B/C``) get frequency 0 and sink to the bottom.

Output: ``data/interim/abbreviations_ranked.csv``.

Usage
-----
    python training/prepare_abbreviations.py
    python training/prepare_abbreviations.py --top 100
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from wordfreq import tokenize, zipf_frequency

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = _PROJECT_ROOT / "data" / "raw" / "txt-sms-abbreviations" / "sms.csv"
OUT_CSV = _PROJECT_ROOT / "data" / "interim" / "abbreviations_ranked.csv"

_HAS_LETTER = re.compile(r"[A-Za-z]")


def abbreviation_frequency(abbr: str) -> float:
    """Zipf frequency of *abbr* as a single token, or 0 if wordfreq splits it."""
    tokens = tokenize(abbr, "en")
    if tokens != [abbr.lower()]:
        return 0.0
    return zipf_frequency(abbr, "en")


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter and rank the SMS abbreviation list.")
    parser.add_argument("--top", type=int, default=100, help="How many top rows to print (default: 100)")
    args = parser.parse_args()

    with RAW_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)

    is_word = [r for r in rows if r["IsWord"].strip().lower() == "true"]
    rows = [r for r in rows if r["IsWord"].strip().lower() != "true"]
    no_letters = [r for r in rows if not _HAS_LETTER.search(r["Abbreviation"])]
    rows = [r for r in rows if _HAS_LETTER.search(r["Abbreviation"])]

    seen: set[str] = set()
    unique = []
    for r in rows:
        key = r["Abbreviation"].strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    duplicates = len(rows) - len(unique)

    ranked = sorted(
        ({"abbreviation": r["Abbreviation"].strip(),
          "expansion": r["Expansion"].strip(),
          "zipf": abbreviation_frequency(r["Abbreviation"].strip())} for r in unique),
        key=lambda r: (-r["zipf"], r["abbreviation"].lower()),
    )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["abbreviation", "expansion", "zipf"])
        writer.writeheader()
        writer.writerows(ranked)

    print(f"Total rows:            {total}")
    print(f"Dropped IsWord=True:   {len(is_word)}")
    print(f"Dropped no letters:    {len(no_letters)}")
    print(f"Dropped duplicates:    {duplicates}")
    print(f"Remaining:             {len(ranked)}  (zipf > 0: {sum(r['zipf'] > 0 for r in ranked)})")
    print(f"Saved to {OUT_CSV.relative_to(_PROJECT_ROOT)}\n")

    for i, r in enumerate(ranked[:args.top], 1):
        print(f"{i:3}. {r['abbreviation']:<10} {r['zipf']:.2f}  {r['expansion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
