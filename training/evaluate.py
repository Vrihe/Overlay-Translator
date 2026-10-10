"""
training/evaluate.py — stage 4 of the NLLB fine-tune: compare models on the
held-out test set with chrF, separately for abbreviation and general pairs.

Every system translates the same ``data/processed/test.jsonl`` with the same
deterministic decoding (beam 4, no sampling, fixed seed). Supported systems:

  name=ct2:<dir>               CTranslate2 int8 build on CPU (what the app runs)
  name=hf:<dir>                fp32 transformers checkpoint
  name=lora:<base dir>+<adapter dir>   fp32 base + peft LoRA adapter

Scores (sacrebleu chrF, beta=2, char_order=6 — same as scripts/baseline_eval_nllb.py)
  * abbr     : pairs whose source contains a test-only abbreviation
               (reference = NLLB translation of the expanded phrase)
  * general  : FLORES-200 dev sentences (human reference)
  * keep_rate: share of "keep" pairs whose term (gg, pvp ...) survives verbatim
  * per-language chrF, and a paired bootstrap 95 % CI for the difference to the
    first system.

Hypotheses and scores go to ``checkpoints/eval/<name>.jsonl`` and ``checkpoints/eval/summary.json``.

Usage
-----
    .venv-train\\Scripts\\python training/evaluate.py \\
        v0-base=ct2:models/nllb-v0-base \\
        base-fp32=hf:D:/projects/overlay-translator/models/nllb-200-distilled-600M \\
        v1-lora=lora:D:/projects/overlay-translator/models/nllb-200-distilled-600M+checkpoints/v1-abbr/adapter
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_JSONL = _PROJECT_ROOT / "data" / "processed" / "test.jsonl"
PHRASES_JSONL = _PROJECT_ROOT / "data" / "interim" / "abbr_phrases.jsonl"
EVAL_DIR = _PROJECT_ROOT / "checkpoints" / "eval"
BEAMS = 4
MAX_NEW_TOKENS = 256


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def by_lang(rows: list[dict]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row["tgt_code"]].append(i)
    return groups


def translate_ct2(model_dir: Path, rows: list[dict], batch_size: int) -> list[str]:
    import ctranslate2
    import sentencepiece as spm

    translator = ctranslate2.Translator(str(model_dir), device="cpu", compute_type="int8")
    sp = spm.SentencePieceProcessor(model_file=str(model_dir / "sentencepiece.bpe.model"))
    out = [""] * len(rows)
    for code, idx in by_lang(rows).items():
        for i in range(0, len(idx), batch_size):
            chunk = idx[i:i + batch_size]
            sources = [["eng_Latn", *sp.encode(rows[j]["src"], out_type=str), "</s>"] for j in chunk]
            results = translator.translate_batch(sources, target_prefix=[[code]] * len(chunk),
                                                 beam_size=BEAMS, max_decoding_length=MAX_NEW_TOKENS)
            for j, res in zip(chunk, results):
                tokens = [t for t in res.hypotheses[0][1:] if t not in ("</s>", "<pad>", "<s>")]
                out[j] = sp.decode(tokens)
    return out


def translate_hf(model_dir: Path, adapter: Path | None, rows: list[dict], batch_size: int) -> list[str]:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, src_lang="eng_Latn")
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir, dtype=torch.float32)
    if adapter is not None:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    model = model.to(device).eval()
    out = [""] * len(rows)
    for code, idx in by_lang(rows).items():
        for i in range(0, len(idx), batch_size):
            chunk = idx[i:i + batch_size]
            enc = tokenizer([rows[j]["src"] for j in chunk], return_tensors="pt", padding=True).to(device)
            with torch.inference_mode():
                gen = model.generate(**enc, forced_bos_token_id=tokenizer.convert_tokens_to_ids(code),
                                     num_beams=BEAMS, do_sample=False, max_new_tokens=MAX_NEW_TOKENS)
            for j, text in zip(chunk, tokenizer.batch_decode(gen, skip_special_tokens=True)):
                out[j] = text
    return out


def keep_ok(hyp: str, terms: list[str]) -> bool:
    return all(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", hyp, re.IGNORECASE) for t in terms)


def score(rows: list[dict], hyps: list[str], keep_terms: set[str]) -> dict:
    from sacrebleu.metrics import CHRF

    chrf = CHRF()

    def corpus(idx: list[int]) -> float:
        return chrf.corpus_score([hyps[i] for i in idx], [[rows[i]["tgt"] for i in idx]]).score

    kinds = {k: [i for i, r in enumerate(rows) if r["kind"] == k] for k in ("abbr", "general")}
    keep_idx = [i for i in kinds["abbr"] if rows[i]["mode"] == "keep"]
    result = {"chrf": {k: round(corpus(v), 2) for k, v in kinds.items()},
              "chrf_by_mode": {m: round(corpus([i for i in kinds["abbr"] if rows[i]["mode"] == m]), 2)
                               for m in ("keep", "translate")},
              "keep_rate": round(100 * sum(keep_ok(hyps[i], [a for a in rows[i]["abbrs"] if a in keep_terms])
                                           for i in keep_idx) / len(keep_idx), 1),
              "chrf_by_lang": {}}
    for kind, idx in kinds.items():
        langs = sorted({rows[i]["lang"] for i in idx})
        result["chrf_by_lang"][kind] = {l: round(corpus([i for i in idx if rows[i]["lang"] == l]), 2)
                                        for l in langs}
    return result


def bootstrap_delta(rows, hyps_a, hyps_b, idx, n=1000, seed=42) -> tuple[float, float, float]:
    """Paired bootstrap of corpus chrF(b) - chrF(a): (delta, 2.5 %, 97.5 %)."""
    from sacrebleu.metrics import CHRF

    chrf = CHRF()

    def stats(hyps):  # per-sentence sufficient statistics; corpus chrF is computed from their sum
        return chrf._extract_corpus_statistics([hyps[i] for i in idx], [[rows[i]["tgt"] for i in idx]])

    sa, sb = stats(hyps_a), stats(hyps_b)

    def corpus(stat_rows):
        return chrf._compute_score_from_stats([sum(col) for col in zip(*stat_rows)]).score

    delta = corpus(sb) - corpus(sa)
    rng = random.Random(seed)
    deltas = []
    for _ in range(n):
        pick = [rng.randrange(len(idx)) for _ in idx]
        deltas.append(corpus([sb[k] for k in pick]) - corpus([sa[k] for k in pick]))
    deltas.sort()
    return round(delta, 2), round(deltas[int(0.025 * n)], 2), round(deltas[int(0.975 * n)], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare NLLB systems on the abbreviation test set.")
    parser.add_argument("systems", nargs="+", help="name=ct2:<dir> | name=hf:<dir> | name=lora:<base>+<adapter>")
    parser.add_argument("--test", type=Path, default=TEST_JSONL)
    parser.add_argument("--out-dir", type=Path, default=EVAL_DIR, help="where hypotheses and summary.json go")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu-mem-fraction", type=float, default=0.8,
                        help="hard cap on this process's share of GPU memory")
    parser.add_argument("--reuse", action="store_true", help="reuse saved hypotheses in checkpoints/eval/")
    args = parser.parse_args()

    import torch
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(args.gpu_mem_fraction)
    torch.manual_seed(args.seed)
    random.seed(args.seed)

    rows = load_jsonl(args.test)
    keep_terms = {p["abbr"].lower() for p in load_jsonl(PHRASES_JSONL) if p["mode"] == "keep"}
    eval_dir = args.out_dir if args.out_dir.is_absolute() else _PROJECT_ROOT / args.out_dir
    eval_dir.mkdir(parents=True, exist_ok=True)

    hyps: dict[str, list[str]] = {}
    timing: dict[str, float] = {}
    for spec in args.systems:
        name, _, target = spec.partition("=")
        kind, _, path = target.partition(":")
        out_path = eval_dir / f"{name}.jsonl"
        if args.reuse and out_path.exists():
            hyps[name] = [json.loads(l)["hyp"] for l in out_path.read_text(encoding="utf-8").splitlines()]
            print(f"[{name}] reused {out_path.relative_to(_PROJECT_ROOT)}", flush=True)
            continue
        started = time.time()
        if kind == "ct2":
            hyps[name] = translate_ct2(Path(path), rows, args.batch_size)
        elif kind == "hf":
            hyps[name] = translate_hf(Path(path), None, rows, args.batch_size)
        elif kind == "lora":
            base, _, adapter = path.partition("+")
            hyps[name] = translate_hf(Path(base), Path(adapter), rows, args.batch_size)
        else:
            print(f"unknown system type: {spec}", file=sys.stderr)
            return 1
        timing[name] = round(time.time() - started, 1)
        with out_path.open("w", encoding="utf-8") as f:
            for row, hyp in zip(rows, hyps[name]):
                f.write(json.dumps({**row, "hyp": hyp}, ensure_ascii=False) + "\n")
        print(f"[{name}] translated {len(rows)} pairs in {timing[name]}s", flush=True)

    names = list(hyps)
    summary = {"test": str(args.test), "pairs": len(rows), "seed": args.seed,
               "beams": BEAMS, "systems": {}}
    for name in names:
        summary["systems"][name] = {"spec": next(s for s in args.systems if s.startswith(name + "=")),
                                    **score(rows, hyps[name], keep_terms)}
    ref = names[0]
    for name in names[1:]:
        summary["systems"][name]["delta_vs_" + ref] = {
            kind: bootstrap_delta(rows, hyps[ref], hyps[name], [i for i, r in enumerate(rows) if r["kind"] == kind])
            for kind in ("abbr", "general")}
    (eval_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
