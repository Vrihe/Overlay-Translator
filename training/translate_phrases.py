"""
training/translate_phrases.py — stage 2.2 of the NLLB fine-tune: translate the
full (expanded) game-chat phrases into the target languages with the local
fp32 NLLB checkpoint (Hugging Face transformers).

Input : ``data/interim/abbr_phrases.jsonl`` (built by ``training/abbr_phrases.py``)
Output: ``data/interim/abbr_translations.jsonl``, one line per (phrase, language)::

    {"full": "be right back, doorbell", "lang": "ru", "text": "...",
     "keep_terms": ["..."], "keep_ok": true}

``keep_terms`` are the "keep" abbreviations found in the phrase (gg, dps, lfg ...);
``keep_ok`` says whether all of them survived verbatim in the translation.
The script resumes: pairs already in the output file are skipped.

NLLB often drops or transliterates these terms ("gg" -> "ГГ", "nerf" -> "нерв").
``--repair-keep`` retranslates every ``keep_ok == false`` row with the terms
masked as ``[1]``, ``[2]`` ..., which NLLB copies verbatim, then puts the terms
back in their original spelling. Rows whose placeholders survived get
``keep_ok: true, repaired: true``; the rest stay as they were.

Usage
-----
    python training/translate_phrases.py
    python training/translate_phrases.py --langs ru uk --batch-size 16
    python training/translate_phrases.py --repair-keep
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
IN_JSONL = _PROJECT_ROOT / "data" / "interim" / "abbr_phrases.jsonl"
OUT_JSONL = _PROJECT_ROOT / "data" / "interim" / "abbr_translations.jsonl"
DEFAULT_MODEL = Path(r"D:\projects\overlay-translator\models\nllb-200-distilled-600M")

# Target languages of the fine-tune -> NLLB (FLORES-200) codes.
LANGS = {
    "de": "deu_Latn", "fr": "fra_Latn", "es": "spa_Latn",
    "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "be": "bel_Cyrl",
    "pl": "pol_Latn", "cs": "ces_Latn", "hu": "hun_Latn",
}


def find_keep_terms(text: str, keep_abbrs: set[str]) -> list[str]:
    words = {w.lower() for w in re.findall(r"[\w']+", text)}
    return sorted(words & keep_abbrs)


def keep_terms_ok(translation: str, terms: list[str]) -> bool:
    return all(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", translation, re.IGNORECASE) for t in terms)


def mask_terms(text: str, terms: list[str]) -> tuple[str, dict[str, str]]:
    """Replace each keep term with ``[n]``; return the masked text and placeholder -> original spelling."""
    restore: dict[str, str] = {}
    for n, term in enumerate(terms, 1):
        placeholder = f"[{n}]"
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            restore[placeholder] = found.group(0)
            text = re.sub(pattern, placeholder, text, flags=re.IGNORECASE)
    return text, restore


def unmask_terms(translation: str, restore: dict[str, str]) -> str | None:
    """Put the original terms back; None if any placeholder got lost."""
    if not all(ph in translation for ph in restore):
        return None
    for placeholder, original in restore.items():
        translation = translation.replace(placeholder, original)
    return translation


def translate_batch(model, tokenizer, texts: list[str], lang: str, beams: int) -> list[str]:
    import torch

    enc = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
    with torch.inference_mode():
        gen = model.generate(**enc, forced_bos_token_id=tokenizer.convert_tokens_to_ids(LANGS[lang]),
                             num_beams=beams, max_new_tokens=128)
    return tokenizer.batch_decode(gen, skip_special_tokens=True)


def repair_keep(model, tokenizer, batch_size: int, beams: int) -> None:
    rows = [json.loads(line) for line in OUT_JSONL.read_text(encoding="utf-8").splitlines()]
    for lang in LANGS:
        todo = [r for r in rows if r["lang"] == lang and not r["keep_ok"]]
        fixed = 0
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            masked = [mask_terms(r["full"], r["keep_terms"]) for r in batch]
            outputs = translate_batch(model, tokenizer, [m[0] for m in masked], lang, beams)
            for row, (_, restore), text in zip(batch, masked, outputs):
                restored = unmask_terms(text, restore)
                if restored is not None and keep_terms_ok(restored, row["keep_terms"]):
                    row.update(text=restored, keep_ok=True, repaired=True)
                    fixed += 1
        print(f"[{lang}] repaired {fixed}/{len(todo)}", flush=True)
    with OUT_JSONL.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate full game-chat phrases with local NLLB.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="fp32 NLLB checkpoint directory")
    parser.add_argument("--langs", nargs="+", default=list(LANGS), choices=list(LANGS))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--beams", type=int, default=4)
    parser.add_argument("--repair-keep", action="store_true",
                        help="retranslate rows that lost a keep term, with the terms masked as [n]")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    phrases = [json.loads(line) for line in IN_JSONL.read_text(encoding="utf-8").splitlines()]
    keep_abbrs = {p["abbr"].lower() for p in phrases if p["mode"] == "keep"}
    sources = sorted({p["full"] for p in phrases})

    done: set[tuple[str, str]] = set()
    if OUT_JSONL.exists():
        for line in OUT_JSONL.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["full"], row["lang"]))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(0)
    print(f"Loading {args.model} on {device} ...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, src_lang="eng_Latn")
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model).to(device).eval()

    if args.repair_keep:
        repair_keep(model, tokenizer, args.batch_size, args.beams)
        return 0

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open("a", encoding="utf-8") as out:
        for lang in args.langs:
            todo = [s for s in sources if (s, lang) not in done]
            if not todo:
                print(f"[{lang}] already done", flush=True)
                continue
            started, lost = time.time(), 0
            for i in range(0, len(todo), args.batch_size):
                batch = todo[i:i + args.batch_size]
                for src, text in zip(batch, translate_batch(model, tokenizer, batch, lang, args.beams)):
                    terms = find_keep_terms(src, keep_abbrs)
                    ok = keep_terms_ok(text, terms)
                    lost += not ok
                    out.write(json.dumps({"full": src, "lang": lang, "text": text,
                                          "keep_terms": terms, "keep_ok": ok}, ensure_ascii=False) + "\n")
                out.flush()
                print(f"[{lang}] {min(i + args.batch_size, len(todo))}/{len(todo)}", flush=True)
            print(f"[{lang}] done in {time.time() - started:.0f}s, keep terms lost in {lost} phrases", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
