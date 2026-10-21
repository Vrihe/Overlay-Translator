"""
training/merge_lora.py — stage 5.1 of the NLLB fine-tune: fold the LoRA adapter
into the base weights (``merge_and_unload``) and save a plain fp32 checkpoint
that ``ct2-transformers-converter`` can read.

The tokenizer files are copied byte-for-byte from the base checkpoint (not
re-saved by transformers), so the converted model gets exactly the same
tokenizer as v0-base.

Usage
-----
    .venv-train\\Scripts\\python training/merge_lora.py \\
        --adapter checkpoints/v1-final-b/adapter --out models/nllb-finetuned-v1-merged

then convert as for v0-base:

    ct2-transformers-converter --model models/nllb-finetuned-v1-merged \\
        --output_dir models/nllb-v1-abbr-ct2-int8 --quantization int8 \\
        --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json \\
                     sentencepiece.bpe.model generation_config.json
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# fp32 HF checkpoint; override with --base or the NLLB_BASE_MODEL_DIR env var
DEFAULT_BASE = Path(os.environ.get("NLLB_BASE_MODEL_DIR") or _PROJECT_ROOT / "models" / "nllb-200-distilled-600M")
TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "generation_config.json",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge a LoRA adapter into the NLLB base weights.")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="fp32 NLLB checkpoint directory")
    parser.add_argument("--adapter", type=Path, required=True, help="peft adapter directory")
    parser.add_argument("--out", type=Path, required=True, help="output directory for the merged checkpoint")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForSeq2SeqLM

    out = args.out if args.out.is_absolute() else _PROJECT_ROOT / args.out
    if out.exists() and any(out.iterdir()):
        print(f"{out} is not empty; remove it first", file=sys.stderr)
        return 1

    base = AutoModelForSeq2SeqLM.from_pretrained(args.base, dtype=torch.float32)
    reference = {k: v.clone() for k, v in base.state_dict().items() if "q_proj.weight" in k}
    model = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()

    # Sanity check: the merge must actually change the attention weights.
    changed = sum(not torch.equal(reference[k], v) for k, v in model.state_dict().items() if k in reference)
    print(f"q_proj matrices changed by the merge: {changed}/{len(reference)}")
    if changed != len(reference):
        print("merge did not touch every q_proj; check the adapter", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out, safe_serialization=True)
    for name in TOKENIZER_FILES:
        shutil.copy2(args.base / name, out / name)
    print(f"Merged checkpoint saved to {out}")
    for f in sorted(out.iterdir()):
        print(f"  {f.name:28} {f.stat().st_size / 2**20:8.1f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
