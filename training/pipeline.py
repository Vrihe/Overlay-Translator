"""
training/pipeline.py — one command per stage of the NLLB fine-tune, driven by a YAML config.

Stages (in order): data → train → merge → convert → eval; `all` runs every stage.

    data     deletes `data.clean` (resumable outputs), then runs `data.steps`, each a
             training/*.py script with its arguments
    train    training/finetune_lora.py --config <config>
    merge    training/merge_lora.py: adapter + base → merged fp32 checkpoint
    convert  CTranslate2 converter: merged checkpoint → int8 build (what the app ships)
    eval     training/evaluate.py on every `eval.test` file, int8 build on the CPU

Usage (run with the training venv, from anywhere):
    .venv-train\\Scripts\\python training/pipeline.py all --config configs/train/v2.yaml
    .venv-train\\Scripts\\python training/pipeline.py train --config configs/train/v1.yaml --name v1-repro
    .venv-train\\Scripts\\python training/pipeline.py all --config configs/train/v2.yaml --dry-run

--name renames the run, so every derived path ({name} in the config) points to fresh
directories and a reproduction never overwrites a published run. Stages that would
overwrite an existing checkpoint or model refuse to run unless --force is given.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_config import PROJECT_ROOT, ConfigError, load_config, resolve  # noqa: E402

STAGES = ("data", "train", "merge", "convert", "eval")
CHECKPOINTS = PROJECT_ROOT / "checkpoints"
# tokenizer files the app needs next to model.bin
CT2_COPY_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "generation_config.json",
]


class StageError(RuntimeError):
    """A stage cannot run as configured (missing section, output already exists)."""


def _python(script: str, *args: str) -> list[str]:
    return [sys.executable, str(resolve(script)), *args]


def _guard(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise StageError(f"{path} already exists; pick another --name or pass --force")


def _section(cfg: dict, name: str) -> dict:
    if name not in cfg:
        raise StageError(f"the config has no '{name}' section")
    return cfg[name]


def clean_paths(cfg: dict) -> list[Path]:
    """Files the data stage deletes first, so resumable scripts rebuild them from scratch."""
    data_root = PROJECT_ROOT / "data"
    paths = [resolve(p) for p in cfg["data"].get("clean", [])]
    for path in paths:
        if data_root not in path.resolve().parents:
            raise StageError(f"data.clean may only list files under data/: {path}")
    return paths


def stage_commands(cfg: dict, stage: str, force: bool = False) -> list[list[str]]:
    """Commands of one stage; checks outputs that must not be overwritten."""
    name = cfg["name"]
    adapter = CHECKPOINTS / name / "adapter"
    if stage == "data":
        return [_python(*shlex.split(step)) for step in cfg["data"].get("steps", [])]
    if stage == "train":
        _guard(adapter, force)
        return [_python("training/finetune_lora.py", "--config", str(cfg["config_path"]), "--run-name", name)]
    if stage == "merge":
        out = resolve(_section(cfg, "merge")["out"])
        _guard(out, force)
        return [
            _python(
                "training/merge_lora.py",
                "--base",
                str(resolve(cfg["base_model"])),
                "--adapter",
                str(adapter),
                "--out",
                str(out),
            )
        ]
    if stage == "convert":
        conv = _section(cfg, "convert")
        out = resolve(conv["out"])
        _guard(out, force)
        cmd = [sys.executable, "-m", "ctranslate2.converters.transformers"]
        cmd += ["--model", str(resolve(_section(cfg, "merge")["out"])), "--output_dir", str(out)]
        cmd += ["--quantization", conv.get("quantization", "int8")]
        cmd += ["--copy_files", *conv.get("copy_files", CT2_COPY_FILES)]
        return [cmd + (["--force"] if force else [])]
    if stage == "eval":
        ev = _section(cfg, "eval")
        tests = ev["test"] if isinstance(ev["test"], list) else [ev["test"]]
        out_dir = resolve(ev.get("out_dir", f"checkpoints/eval_{name}"))
        systems = [f"{sys_name}={spec}" for sys_name, spec in ev["systems"].items()]
        cmds = []
        for test in tests:
            cmd = _python(
                "training/evaluate.py", "--test", str(resolve(test)), "--out-dir", str(out_dir / Path(test).stem)
            )
            if "batch_size" in ev:
                cmd += ["--batch-size", str(ev["batch_size"])]
            cmds.append(cmd + systems)
        return cmds
    raise StageError(f"unknown stage {stage!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the NLLB fine-tune pipeline from a YAML config.")
    parser.add_argument("stage", choices=(*STAGES, "all"))
    parser.add_argument("--config", type=Path, required=True, help="configs/train/<version>.yaml")
    parser.add_argument("--name", default=None, help="run name; overrides the config's `name`")
    parser.add_argument("--force", action="store_true", help="overwrite existing checkpoints and models")
    parser.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config.resolve(), args.name)
        stages = STAGES if args.stage == "all" else (args.stage,)
        # each stage is planned only when it starts: its guards see what earlier stages wrote
        for stage in stages:
            if stage == "data":
                for path in clean_paths(cfg):
                    print(f"[data] delete {path}", flush=True)
                    if not args.dry_run:
                        path.unlink(missing_ok=True)
            for cmd in stage_commands(cfg, stage, args.force):
                print(f"[{stage}] {shlex.join(cmd)}", flush=True)
                if not args.dry_run:
                    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except (ConfigError, StageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
