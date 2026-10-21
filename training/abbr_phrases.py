"""
training/abbr_phrases.py — parse and validate ``training/abbr_phrases.txt``.

``load_phrases()`` returns one dict per phrase::

    {"abbr": "brb", "mode": "translate", "expansion": "be right back",
     "source": "dataset" | "added", "short": "brb, doorbell",
     "full": "be right back, doorbell"}

Run as a script to validate the file and write ``data/interim/abbr_phrases.jsonl``.

Checks:
  * every phrase contains its abbreviation as a whole word (case-insensitive);
  * ``translate`` phrases have a full version without the abbreviation;
  * ``keep`` phrases have no ``=>`` (full == short);
  * 3-5 phrases per abbreviation, no duplicate abbreviations or phrases.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PHRASES_TXT = Path(__file__).resolve().parent / "abbr_phrases.txt"
OUT_JSONL = _PROJECT_ROOT / "data" / "interim" / "abbr_phrases.jsonl"

MODES = ("keep", "translate")


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", text, re.IGNORECASE) is not None


def load_phrases(path: Path = PHRASES_TXT) -> list[dict]:
    phrases: list[dict] = []
    header: dict | None = None
    errors: list[str] = []

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("## ")):
            continue
        if line.startswith("## "):
            parts = [p.strip() for p in line[3:].split("|")]
            if len(parts) not in (3, 4) or parts[1] not in MODES:
                errors.append(f"{lineno}: bad header: {line}")
                header = None
                continue
            header = {
                "abbr": parts[0],
                "mode": parts[1],
                "expansion": parts[2],
                "source": "added" if len(parts) == 4 and parts[3] == "added" else "dataset",
            }
            continue
        if header is None:
            errors.append(f"{lineno}: phrase outside a section: {line}")
            continue

        if "=>" in line:
            short, full = (s.strip() for s in line.split("=>", 1))
        else:
            short, full = line, line

        abbr, mode = header["abbr"], header["mode"]
        if not _contains_word(short, abbr):
            errors.append(f"{lineno}: '{abbr}' not found in: {short}")
        if mode == "keep" and short != full:
            errors.append(f"{lineno}: keep phrase must not have '=>': {line}")
        if mode == "translate" and (short == full or _contains_word(full, abbr)):
            errors.append(f"{lineno}: '{abbr}' is not expanded in: {full}")

        phrases.append({**header, "short": short, "full": full})

    per_abbr = Counter(p["abbr"] for p in phrases)
    errors += [f"'{a}': {n} phrases (need 3-5)" for a, n in per_abbr.items() if not 3 <= n <= 5]
    errors += [f"duplicate phrase: {s}" for s, n in Counter(p["short"].lower() for p in phrases).items() if n > 1]
    headers = [
        ln[3:].split("|")[0].strip().lower()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.startswith("## ")
    ]
    errors += [f"duplicate section: {a}" for a, n in Counter(headers).items() if n > 1]

    if errors:
        raise ValueError("abbr_phrases.txt is invalid:\n  " + "\n  ".join(errors))
    return phrases


def main() -> int:
    try:
        phrases = load_phrases()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for p in phrases:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    abbrs = {p["abbr"]: p for p in phrases}
    by_mode = Counter(p["mode"] for p in abbrs.values())
    by_source = Counter(p["source"] for p in abbrs.values())
    print(
        f"Abbreviations: {len(abbrs)}  (keep {by_mode['keep']}, translate {by_mode['translate']}; "
        f"dataset {by_source['dataset']}, added {by_source['added']})"
    )
    print(
        f"Phrases:       {len(phrases)}  (keep {sum(p['mode'] == 'keep' for p in phrases)}, "
        f"translate {sum(p['mode'] == 'translate' for p in phrases)})"
    )
    print(f"Saved to {OUT_JSONL.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
