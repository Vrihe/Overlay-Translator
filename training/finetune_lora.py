"""
training/finetune_lora.py — stage 3 of the NLLB fine-tune: LoRA on the
attention layers of NLLB-200-distilled-600M (transformers + peft, bf16).

Data  : data/processed/{train,val}.jsonl (training/build_dataset.py), or --data-dir
Output: checkpoints/<run-name>/
          checkpoint-<step>/   Trainer checkpoints (adapter + optimizer state)
          adapter/             final LoRA adapter (peft format)
          log.jsonl            loss / eval_loss / lr / VRAM / speed per logging step
          run_config.json      arguments, seed, data sizes, trainable params

LoRA goes on q/k/v/out projections of every self- and cross-attention block.
The base model is loaded in fp32 and trained under bf16 autocast; only the
adapter weights get gradients. Memory is dominated by the logits over the
256k-token vocabulary, hence batch 4 x grad-accum 4 (effective 16).

GPU load is capped for the duration of training only (nothing system-wide changes):
  * --gpu-mem-fraction 0.9: hard cap on this process's share of VRAM;
  * --gpu-duty 0.9: after every optimizer step the trainer sleeps long enough that the
    GPU is busy at most 90 % of the wall-clock time (a power limit via nvidia-smi
    would need admin rights).

Usage (run with the CUDA venv, see requirements-train.txt)
-----
    .venv-train\\Scripts\\python training/finetune_lora.py --max-steps 50 --run-name trial
    .venv-train\\Scripts\\python training/finetune_lora.py --epochs 3 --run-name v1-abbr
    .venv-train\\Scripts\\python training/finetune_lora.py --data-dir data/processed_v2 --run-name v2-game \\
        --lora-r 32 --lora-alpha 64 --group-by-length
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PROJECT_ROOT / "data" / "processed"
CHECKPOINTS = _PROJECT_ROOT / "checkpoints"
# fp32 HF checkpoint; override with --model or the NLLB_BASE_MODEL_DIR env var
DEFAULT_MODEL = Path(os.environ.get("NLLB_BASE_MODEL_DIR")
                     or _PROJECT_ROOT / "models" / "nllb-200-distilled-600M")
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj"]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def encode(rows: list[dict], tokenizer, max_len: int) -> list[dict]:
    """Source in eng_Latn; labels start with the row's target language token."""
    out = []
    for row in rows:
        tokenizer.tgt_lang = row["tgt_code"]
        enc = tokenizer(row["src"], text_target=row["tgt"], max_length=max_len, truncation=True)
        out.append({"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"],
                    "labels": enc["labels"]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="LoRA fine-tune of NLLB on game-chat abbreviations.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="fp32 NLLB checkpoint directory")
    parser.add_argument("--run-name", default="v1-abbr")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="directory with train/val.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--max-steps", type=int, default=-1, help="overrides --epochs when > 0 (trial runs)")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--eval-batch-size", type=int, default=None,
                        help="default 2 x --batch-size; lower it when the long FLORES val sentences OOM")
    parser.add_argument("--grad-accum", type=int, default=4, help="effective batch = batch-size * grad-accum")
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--warmup-steps", type=int, default=30)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--max-len", type=int, default=128)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--eval-steps", type=int, default=100)
    parser.add_argument("--resume", type=Path, default=None,
                        help="checkpoint-<step> directory of this run to continue from (same arguments)")
    parser.add_argument("--group-by-length", action="store_true",
                        help="batch pairs of similar length (less padding; short chat phrases dominate v2)")
    parser.add_argument("--gpu-mem-fraction", type=float, default=0.9,
                        help="hard cap on this process's share of GPU memory")
    parser.add_argument("--gpu-duty", type=float, default=0.9,
                        help="max share of wall-clock time the GPU computes; 1 disables throttling")
    args = parser.parse_args()

    # The 256k-token vocabulary makes the logits the largest tensor by far
    # (batch x seq x 256k, cast to fp32); expandable segments avoid OOM from fragmentation.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer, DataCollatorForSeq2Seq,
                              Seq2SeqTrainer, Seq2SeqTrainingArguments, TrainerCallback, set_seed)

    if not torch.cuda.is_available():
        print("CUDA is not available; run with .venv-train (see requirements-train.txt)", file=sys.stderr)
        return 1
    torch.cuda.set_per_process_memory_fraction(args.gpu_mem_fraction)
    set_seed(args.seed)
    out_dir = CHECKPOINTS / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.model, src_lang="eng_Latn")
    train_rows, val_rows = load_jsonl(args.data_dir / "train.jsonl"), load_jsonl(args.data_dir / "val.jsonl")
    train_ds, val_ds = encode(train_rows, tokenizer, args.max_len), encode(val_rows, tokenizer, args.max_len)

    model = AutoModelForSeq2SeqLM.from_pretrained(args.model, dtype=torch.float32)
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_2_SEQ_LM, r=args.lora_r, lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout, target_modules=LORA_TARGETS))
    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable params: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)", flush=True)

    log_path = out_dir / "log.jsonl"
    if args.resume is None:
        log_path.unlink(missing_ok=True)  # a resumed run appends to its log

    class LogCallback(TrainerCallback):
        """Append every log record with peak VRAM and wall-clock speed to log.jsonl."""

        def on_train_begin(self, args_, state, control, **kwargs):
            torch.cuda.reset_peak_memory_stats()
            self.started = time.time()
            self.first_step = state.global_step  # > 0 when resumed

        def on_log(self, args_, state, control, logs=None, **kwargs):
            elapsed = time.time() - self.started
            record = {"step": state.global_step, "epoch": round(state.epoch or 0, 3), **(logs or {}),
                      "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                      "vram_reserved_gb": round(torch.cuda.max_memory_reserved() / 2**30, 2),
                      "elapsed_s": round(elapsed, 1),
                      "steps_per_s": round((state.global_step - self.first_step) / elapsed, 2) if elapsed else None}
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    class DutyCycleCallback(TrainerCallback):
        """Sleep after each optimizer step so GPU compute takes at most --gpu-duty of the time."""

        def on_step_begin(self, args_, state, control, **kwargs):
            self.step_started = time.perf_counter()

        def on_step_end(self, args_, state, control, **kwargs):
            torch.cuda.synchronize()
            busy = time.perf_counter() - self.step_started
            time.sleep(busy * (1 - args.gpu_duty) / args.gpu_duty)

    callbacks = [LogCallback()] + ([DutyCycleCallback()] if args.gpu_duty < 1 else [])

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(out_dir),
        seed=args.seed,
        data_seed=args.seed,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.eval_batch_size or args.batch_size * 2,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="linear",
        warmup_steps=args.warmup_steps,
        bf16=True,
        logging_steps=args.logging_steps,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.eval_steps,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        # only eval_loss is used; otherwise the Trainer keeps every val batch's fp32 logits
        # (batch x seq x 256k) on the GPU, which OOMs with the larger v2 val set
        prediction_loss_only=True,
        dataloader_num_workers=0,
        train_sampling_strategy="group_by_length" if args.group_by_length else "random",
        report_to="none",
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model, padding=True),
        processing_class=tokenizer,
        callbacks=callbacks,
    )
    # PeftModel.forward takes **kwargs, so Trainer assumes the model normalises the loss by
    # num_items_in_batch itself and skips dividing by grad-accum. M2M100 ignores that kwarg,
    # which would sum (not average) the micro-batch losses: logged loss and gradients x grad-accum.
    trainer.model_accepts_loss_kwargs = False

    started = time.time()
    result = trainer.train(resume_from_checkpoint=str(args.resume) if args.resume else None)
    elapsed = time.time() - started
    final_eval = trainer.evaluate()

    model.save_pretrained(out_dir / "adapter")
    tokenizer.save_pretrained(out_dir / "adapter")
    summary = {
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "lora_targets": LORA_TARGETS,
        "train_pairs": len(train_ds), "val_pairs": len(val_ds),
        "trainable_params": trainable, "total_params": total,
        "steps": result.global_step, "train_loss": result.training_loss,
        "eval_loss": final_eval["eval_loss"], "best_checkpoint": trainer.state.best_model_checkpoint,
        "train_time_s": round(elapsed, 1), "steps_per_s": round((result.global_step - (int(args.resume.name.rsplit("-", 1)[1])
                                                    if args.resume else 0)) / elapsed, 2),
        "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "vram_reserved_gb": round(torch.cuda.max_memory_reserved() / 2**30, 2),
        "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__,
    }
    (out_dir / "run_config.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
