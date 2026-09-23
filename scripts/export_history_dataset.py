"""
scripts/export_history_dataset.py — export translation history to a fine-tune JSONL.

Reads the app's SQLite history (the ``translations`` table written by
``cache/store.py``) and emits one JSON object per line:

    {"source": "...", "target": "...", "src_lang": "en", "tgt_lang": "ru"}

Schema actually present in the DB (verified, not assumed):

    translations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_text     TEXT NOT NULL,
        source_lang     TEXT NOT NULL,     -- ISO 639-1, or "_auto" / "auto"
        target_lang     TEXT NOT NULL,
        domain_id       TEXT NOT NULL DEFAULT 'general',
        translated_text TEXT NOT NULL,
        timestamp       REAL NOT NULL,
        UNIQUE(source_text, source_lang, target_lang, domain_id)
    )

Rows are filtered so the dataset stays usable as fine-tuning supervision:

  • ``domain_id`` ending in ``|nllb`` is dropped — those rows are the local
    model's own output, and training on them is self-distillation of errors.
    (Use ``--include-nllb`` to keep them anyway, e.g. for eval comparisons.)
  • Rows where source == target are dropped: they come from the "same language"
    fast path and carry no translation signal.
  • Blank, whitespace-only, and duplicate pairs are dropped.

``source_lang`` of ``"_auto"``/``"auto"`` means the language was never recorded.
Those rows are re-detected offline with the same langid + script heuristic the
app uses (``translate.lang_detect``), so the exported ``src_lang`` is always a
concrete code. Use ``--drop-unknown-src`` to discard them instead.

Usage
-----
    python scripts/export_history_dataset.py
    python scripts/export_history_dataset.py --out data/history.jsonl --val-ratio 0.1
    python scripts/export_history_dataset.py --lang-format flores --with-metadata
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

# Make the project root importable when run as `python scripts/...`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

AUTO_MARKERS = {"_auto", "auto", ""}
NLLB_DOMAIN_SUFFIX = "|nllb"


def default_db_path() -> Path:
    """Locate translations.db the same way ``config``/``cache.store`` do."""
    override = os.environ.get("CACHE_DIR")
    if override:
        return Path(override) / "translations.db"

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "translator-overlay" / "cache" / "translations.db"
    return Path.home() / ".config" / "translator-overlay" / "cache" / "translations.db"


def load_rows(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, source_text, source_lang, target_lang, domain_id, "
            "       translated_text, timestamp "
            "FROM translations ORDER BY timestamp ASC"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def make_detector():
    """Return a callable(text) -> iso code | None, or None if langid is missing."""
    try:
        from translate.lang_detect import detect_source_lang, get_detector
    except Exception:
        return None

    try:
        detector = get_detector("langid")
    except Exception:
        return None

    def detect(text: str) -> str | None:
        try:
            return detect_source_lang(text, detector)
        except Exception:
            return None

    return detect


def to_flores(code: str) -> str | None:
    from translate.nllb_backend import NLLB_LANG_CODES

    return NLLB_LANG_CODES.get((code or "").strip().lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=None,
                        help="path to translations.db (default: app user-data dir)")
    parser.add_argument("--out", type=Path, default=_PROJECT_ROOT / "data" / "history_pairs.jsonl",
                        help="output .jsonl path (default: data/history_pairs.jsonl)")
    parser.add_argument("--min-chars", type=int, default=2,
                        help="skip pairs whose source is shorter than this (default: 2)")
    parser.add_argument("--domain", action="append", default=None,
                        help="keep only this domain_id (repeatable)")
    parser.add_argument("--include-nllb", action="store_true",
                        help="keep rows produced by the local NLLB backend")
    parser.add_argument("--drop-unknown-src", action="store_true",
                        help="drop rows with an unrecorded source language instead of detecting it")
    parser.add_argument("--lang-format", choices=("iso", "flores"), default="iso",
                        help="language code format in the output (default: iso)")
    parser.add_argument("--with-metadata", action="store_true",
                        help="also emit domain_id / timestamp / row id per line")
    parser.add_argument("--val-ratio", type=float, default=0.0,
                        help="if >0, also write a *.val.jsonl holdout of this fraction")
    parser.add_argument("--seed", type=int, default=13, help="shuffle seed for the split")
    args = parser.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        print(f"[FAIL] History DB not found: {db_path}", file=sys.stderr)
        return 1

    rows = load_rows(db_path)
    print(f"DB          : {db_path}")
    print(f"Rows in DB  : {len(rows)}")

    detect = None if args.drop_unknown_src else make_detector()
    if detect is None and not args.drop_unknown_src:
        print("[warn] langid unavailable — rows with an unknown source language will be skipped")

    stats = {
        "nllb_rows": 0,
        "domain_filtered": 0,
        "empty": 0,
        "too_short": 0,
        "identical": 0,
        "unknown_src": 0,
        "unmapped_lang": 0,
        "duplicate": 0,
    }

    seen: set[tuple[str, str, str, str]] = set()
    records: list[dict] = []

    for row in rows:
        domain = (row["domain_id"] or "general").strip()

        if domain.endswith(NLLB_DOMAIN_SUFFIX) and not args.include_nllb:
            stats["nllb_rows"] += 1
            continue

        base_domain = domain[: -len(NLLB_DOMAIN_SUFFIX)] if domain.endswith(NLLB_DOMAIN_SUFFIX) else domain
        if args.domain and base_domain not in args.domain:
            stats["domain_filtered"] += 1
            continue

        source = (row["source_text"] or "").strip()
        target = (row["translated_text"] or "").strip()
        if not source or not target:
            stats["empty"] += 1
            continue
        if len(source) < args.min_chars:
            stats["too_short"] += 1
            continue
        if source == target:
            stats["identical"] += 1
            continue

        src_lang = (row["source_lang"] or "").strip().lower()
        tgt_lang = (row["target_lang"] or "").strip().lower()

        if src_lang in AUTO_MARKERS:
            detected = detect(source) if detect is not None else None
            if not detected:
                stats["unknown_src"] += 1
                continue
            src_lang = detected.strip().lower()

        if src_lang == tgt_lang:
            stats["identical"] += 1
            continue

        out_src, out_tgt = src_lang, tgt_lang
        if args.lang_format == "flores":
            out_src, out_tgt = to_flores(src_lang), to_flores(tgt_lang)
            if not out_src or not out_tgt:
                stats["unmapped_lang"] += 1
                continue

        key = (source, target, src_lang, tgt_lang)
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)

        record = {
            "source": source,
            "target": target,
            "src_lang": out_src,
            "tgt_lang": out_tgt,
        }
        if args.with_metadata:
            record["domain_id"] = base_domain
            record["timestamp"] = row["timestamp"]
            record["history_id"] = row["id"]
        records.append(record)

    print("Kept        :", len(records))
    print("Skipped     :", ", ".join(f"{k}={v}" for k, v in stats.items() if v) or "none")

    if not records:
        print("[FAIL] Nothing to export.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)

    train = records
    val: list[dict] = []
    if args.val_ratio > 0:
        shuffled = list(records)
        random.Random(args.seed).shuffle(shuffled)
        n_val = max(1, round(len(shuffled) * args.val_ratio))
        val, train = shuffled[:n_val], shuffled[n_val:]

    def write(path: Path, items: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Wrote {len(items):5d} pairs -> {path}")

    write(args.out, train)
    if val:
        write(args.out.with_suffix(".val.jsonl"), val)

    pairs: dict[str, int] = {}
    for record in records:
        pairs[f"{record['src_lang']}->{record['tgt_lang']}"] = \
            pairs.get(f"{record['src_lang']}->{record['tgt_lang']}", 0) + 1
    print("Language pairs:")
    for pair, count in sorted(pairs.items(), key=lambda kv: -kv[1]):
        print(f"  {pair:<24} {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
