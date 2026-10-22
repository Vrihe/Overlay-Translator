"""
training/train_config.py — YAML pipeline configs (configs/train/*.yaml) and run provenance.

A config describes one model version end to end:

    name: v2b-game                 # run name; {name} expands in every string below
    base_model: models/nllb-200-distilled-600M
    data:
      dir: data/processed_v2b      # train.jsonl / val.jsonl for the fine-tune
      clean:                       # files under data/ deleted before the steps (resumable outputs)
        - data/interim/v2/game_translations.jsonl
      steps:                       # commands of the data stage, run in order
        - training/build_dataset_v2.py --out-dir data/processed_v2b
    train: {seed: 42, epochs: 5, lora_r: 32, ...}   # finetune_lora.py options
    merge: {out: models/nllb-{name}-merged}
    convert: {out: models/nllb-{name}-ct2-int8, quantization: int8}
    eval:
      test: [data/processed_v2/test_v2.jsonl]
      out_dir: checkpoints/eval_{name}
      systems: {v0-base: "ct2:models/nllb-v0-base", "{name}-int8": "ct2:{convert.out}"}

Besides {name}, strings may reference other values as {section.key} (only `merge.out`,
`convert.out`, `data.dir`, `base_model` and `name`). Relative paths are relative to the
project root. The NLLB_BASE_MODEL_DIR environment variable overrides `base_model`.
Nothing here imports torch: the module is shared by the pipeline runner, finetune_lora.py
and the tests.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "configs" / "train"

# finetune_lora.py options a config may set (argparse dest names)
TRAIN_KEYS = frozenset(
    {
        "seed",
        "epochs",
        "max_steps",
        "batch_size",
        "eval_batch_size",
        "grad_accum",
        "lr",
        "warmup_steps",
        "lora_r",
        "lora_alpha",
        "lora_dropout",
        "max_len",
        "logging_steps",
        "eval_steps",
        "group_by_length",
        "precision",
        "gpu_mem_fraction",
        "gpu_duty",
    }
)
SECTIONS = {
    "name": None,
    "base_model": None,
    "data": {"dir", "steps", "clean"},
    "train": TRAIN_KEYS,
    "merge": {"out"},
    "convert": {"out", "quantization", "copy_files"},
    "eval": {"test", "out_dir", "systems", "batch_size"},
}
REQUIRED = ("name", "base_model", "data", "train")
# libraries whose versions change training or conversion results
TRACKED_LIBS = (
    "torch",
    "transformers",
    "peft",
    "accelerate",
    "tokenizers",
    "sentencepiece",
    "safetensors",
    "ctranslate2",
    "sacrebleu",
)


class ConfigError(ValueError):
    """The config file is malformed or uses unknown keys."""


def _expand(value, refs: dict[str, str]):
    if isinstance(value, str):
        for key, ref in refs.items():
            value = value.replace("{" + key + "}", ref)
        return value
    if isinstance(value, list):
        return [_expand(v, refs) for v in value]
    if isinstance(value, dict):
        return {_expand(k, refs): _expand(v, refs) for k, v in value.items()}
    return value


def parse_config(raw: dict, name: str | None = None) -> dict:
    """Validate a loaded YAML mapping and expand its {references}; `name` overrides `name:`."""
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    unknown = set(raw) - set(SECTIONS)
    if unknown:
        raise ConfigError(f"unknown top-level keys: {sorted(unknown)}")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ConfigError(f"missing keys: {missing}")
    for section, keys in SECTIONS.items():
        if keys is None or section not in raw:
            continue
        if not isinstance(raw[section], dict):
            raise ConfigError(f"'{section}' must be a mapping")
        bad = set(raw[section]) - keys
        if bad:
            raise ConfigError(f"unknown keys in '{section}': {sorted(bad)}")
    if "dir" not in raw["data"]:
        raise ConfigError("'data.dir' is required")

    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()}
    if name:
        cfg["name"] = name
    # the same override every training script honours for the fp32 checkpoint
    cfg["base_model"] = os.environ.get("NLLB_BASE_MODEL_DIR") or cfg["base_model"]
    refs = {"name": str(cfg["name"])}
    refs["base_model"] = _expand(str(cfg["base_model"]), refs)
    refs["data.dir"] = _expand(str(cfg["data"]["dir"]), refs)
    for section in ("merge", "convert"):
        if "out" in cfg.get(section, {}):
            refs[f"{section}.out"] = _expand(str(cfg[section]["out"]), refs)
    return _expand(cfg, refs)


def load_config(path: Path, name: str | None = None) -> dict:
    """Read and validate a YAML config; adds `config_path` and `config_sha256`."""
    import yaml

    text = Path(path).read_text(encoding="utf-8")
    cfg = parse_config(yaml.safe_load(text), name)
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return cfg


def resolve(path: str | Path) -> Path:
    """Project-relative path → absolute path."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def dataset_hash(data_dir: Path, files: tuple[str, ...] = ("train.jsonl", "val.jsonl")) -> str:
    """sha256 over the names and bytes of the split files, so any edit or reorder changes it."""
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update((Path(data_dir) / name).read_bytes())
    return digest.hexdigest()


def git_state(root: Path = PROJECT_ROOT) -> dict:
    """Commit and whether tracked files differ from it.

    Outside a git checkout (the training Docker image) the commit comes from OVERLAY_GIT_SHA
    and `dirty` is unknown.
    """

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.SubprocessError):
        return {"sha": os.environ.get("OVERLAY_GIT_SHA") or None, "dirty": None}


def library_versions(names: tuple[str, ...] = TRACKED_LIBS) -> dict[str, str | None]:
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def provenance(data_dir: Path, config: dict | None = None) -> dict:
    """Everything needed to tell whether two runs started from the same code, data and libraries."""
    info = {
        "git": git_state(),
        "libraries": library_versions(),
        "dataset_sha256": dataset_hash(data_dir),
    }
    if config:
        info["config_path"] = config.get("config_path")
        info["config_sha256"] = config.get("config_sha256")
    return info
