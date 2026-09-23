"""
scripts/test_nllb_translation.py — smoke-test the quantized NLLB CTranslate2 model.

Loads the int8 CTranslate2 build of NLLB-200-distilled-600M, translates a handful
of game-chat style phrases across several language pairs on CPU, and reports
per-phrase inference latency.

Runtime dependencies are only ``ctranslate2`` + ``sentencepiece`` — no torch,
no transformers. That is deliberate: the app must be able to bundle this path
without dragging in the full HF stack.

Usage
-----
    python scripts/test_nllb_translation.py
    python scripts/test_nllb_translation.py --model D:/path/to/nllb-200-ct2-int8
    python scripts/test_nllb_translation.py --threads 4
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_MODEL_DIR = Path(r"D:\projects\overlay-translator\models\nllb-200-ct2-int8")

# ISO 639-1 → FLORES-200 code used by NLLB.
NLLB_LANG_CODES: dict[str, str] = {
    "en": "eng_Latn",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "be": "bel_Cyrl",
    "pl": "pol_Latn",
    "cs": "ces_Latn",
    "hu": "hun_Latn",
}

# (source_lang, target_lang, text) — game / voice-chat register.
SAMPLES: list[tuple[str, str, str]] = [
    ("ru", "en", "го в рейд"),
    ("ru", "de", "нужна помощь"),
    ("en", "ru", "gg wp everyone"),
    ("en", "pl", "need a healer asap, boss is enraged"),
    ("de", "ru", "wo ist der Boss? ich sehe ihn nicht"),
    ("pl", "en", "idziemy na raid za pięć minut"),
    ("uk", "es", "потрібна допомога на базі"),
    ("cs", "hu", "mám málo many, počkejte"),
]


def build_translator(model_dir: Path, threads: int):
    import ctranslate2

    return ctranslate2.Translator(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        inter_threads=1,
        intra_threads=threads,
    )


def build_tokenizer(model_dir: Path):
    import sentencepiece as spm

    sp_model = model_dir / "sentencepiece.bpe.model"
    if not sp_model.exists():
        raise FileNotFoundError(f"sentencepiece.bpe.model not found in {model_dir}")
    return spm.SentencePieceProcessor(model_file=str(sp_model))


def translate(translator, sp, text: str, src_lang: str, tgt_lang: str,
              *, beam_size: int = 4, max_decoding_length: int = 256) -> str:
    """Translate *text* from *src_lang* to *tgt_lang* (ISO 639-1 codes)."""
    src_code = NLLB_LANG_CODES[src_lang]
    tgt_code = NLLB_LANG_CODES[tgt_lang]

    # NLLB input layout: [src_lang] <subword pieces> </s>
    pieces = sp.encode(text, out_type=str)
    source = [src_code] + pieces + ["</s>"]

    results = translator.translate_batch(
        [source],
        target_prefix=[[tgt_code]],
        beam_size=beam_size,
        max_decoding_length=max_decoding_length,
    )
    hypothesis = results[0].hypotheses[0]

    # Drop the forced target-language token and any trailing EOS.
    if hypothesis and hypothesis[0] == tgt_code:
        hypothesis = hypothesis[1:]
    hypothesis = [t for t in hypothesis if t not in ("</s>", "<pad>", "<s>")]

    return sp.decode(hypothesis)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_DIR,
                        help="path to the CTranslate2 model directory")
    parser.add_argument("--threads", type=int, default=min(4, os.cpu_count() or 4),
                        help="intra_threads for CTranslate2 (default: min(4, cpu_count))")
    parser.add_argument("--beam", type=int, default=4, help="beam size (default: 4)")
    args = parser.parse_args()

    model_dir: Path = args.model
    if not model_dir.is_dir():
        print(f"[FAIL] Model directory not found: {model_dir}", file=sys.stderr)
        print("Convert it first with ct2-transformers-converter.", file=sys.stderr)
        return 1

    print(f"Model    : {model_dir}")
    print(f"Threads  : {args.threads}   Beam: {args.beam}")
    print("-" * 78)

    t0 = time.perf_counter()
    translator = build_translator(model_dir, args.threads)
    sp = build_tokenizer(model_dir)
    load_sec = time.perf_counter() - t0
    print(f"Model load: {load_sec:.2f} s")

    # Warm-up run — first call pays for lazy weight paging; keep it out of stats.
    t0 = time.perf_counter()
    translate(translator, sp, "hello", "en", "ru", beam_size=args.beam)
    warmup_sec = time.perf_counter() - t0
    print(f"Warm-up   : {warmup_sec:.2f} s")
    print("-" * 78)

    timings: list[float] = []
    for src, tgt, text in SAMPLES:
        t0 = time.perf_counter()
        out = translate(translator, sp, text, src, tgt, beam_size=args.beam)
        elapsed = time.perf_counter() - t0
        timings.append(elapsed)
        print(f"[{src}->{tgt}] {elapsed * 1000:7.1f} ms")
        print(f"    src: {text}")
        print(f"    out: {out}")

    print("-" * 78)
    n = len(timings)
    print(f"Phrases   : {n}")
    print(f"Total     : {sum(timings):.2f} s")
    print(f"Average   : {sum(timings) / n * 1000:.1f} ms")
    print(f"Min / Max : {min(timings) * 1000:.1f} ms / {max(timings) * 1000:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
