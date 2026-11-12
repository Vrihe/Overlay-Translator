"""
scripts/make_model_card.py — write the Hugging Face model card (``README.md``) of a build.

The card is generated from the build's ``manifest.json`` (files, metrics, channel, minimum app
version) and the few facts that cannot be derived, passed as arguments. Numbers come only from the
manifest: no screen text and no gold lines ever reach the card.

Usage
-----
    python scripts/make_model_card.py models/nllb-v2-game --config configs/train/v2.yaml \\
        --data "Game-chat glossary phrases + FLORES-200 dev" --limitations "Only en -> ru/uk/pl was evaluated."

Run ``scripts/make_manifest.py`` first. Upload the card together with the build, before the tag.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from translate import model_manifest  # noqa: E402

BASE_MODEL = "facebook/nllb-200-distilled-600M"
REPO_URL = "https://github.com/Vrihe/Overlay-Translator"
# NLLB-200 weights are CC-BY-NC 4.0, and a fine-tune inherits that licence.
LICENSE_ID = "cc-by-nc-4.0"

DEFAULT_LIMITATIONS = (
    "- Trained and evaluated for short game-chat lines; long or formal text is not a target.\n"
    "- Non-commercial use only (CC-BY-NC 4.0, inherited from NLLB-200).\n"
    "- Abbreviations outside the training glossary may be translated literally."
)


def _config_lines(config_path: Path | None) -> list[str]:
    """Training settings worth showing, read without a YAML dependency (flat top-level ``key: value`` lines)."""
    if config_path is None:
        return []
    wanted = ("name", "base_model", "seed", "lora_r", "lora_alpha", "learning_rate", "epochs")
    found = []
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        key, sep, value = line.partition(":")
        if sep and key in wanted and value.strip():
            found.append(f"- `{key}`: `{value.strip()}`")
    return found


def build_card(manifest: dict, *, config_path: Path | None, data: str, limitations: str, reproduce: str) -> str:
    """Return the model card text for a parsed ``manifest.json``."""
    version = manifest["version"]
    metrics = manifest.get("metrics", {})
    lines = [
        "---",
        f"license: {LICENSE_ID}",
        f"base_model: {BASE_MODEL}",
        "library_name: ctranslate2",
        "tags: [translation, nllb, ctranslate2, int8, game-chat]",
        "---",
        "",
        f"# Overlay-Translator NLLB — {version}",
        "",
        f"CTranslate2 int8 build of [{BASE_MODEL}](https://huggingface.co/{BASE_MODEL}) for the "
        f"[Overlay-Translator]({REPO_URL}) offline mode.",
        "",
        f"- Channel: `{manifest.get('channel', 'stable')}`",
        f"- Minimum app version: `{manifest.get('min_app_version', '0.0.0')}`",
        "",
        "## Data",
        "",
        data,
        "",
        "## Method",
        "",
        "LoRA fine-tune of the base model, merged and converted to CTranslate2 int8.",
        *_config_lines(config_path),
        "",
        "## Metrics",
        "",
    ]
    if metrics:
        lines += ["| Metric | Value |", "|---|---|"]
        lines += [f"| `{name}` | {value} |" for name, value in sorted(metrics.items())]
    else:
        lines.append("No metrics were recorded for this build.")
    lines += [
        "",
        "## Limitations",
        "",
        limitations,
        "",
        "## License",
        "",
        "CC-BY-NC 4.0, inherited from NLLB-200. Non-commercial use only.",
        "",
        "## How to reproduce",
        "",
        reproduce,
        "",
        "## Files",
        "",
        "| File | Size, bytes | SHA-256 |",
        "|---|---|---|",
        *[f"| `{n}` | {i['size']} | `{i['sha256'][:12]}…` |" for n, i in sorted(manifest["files"].items())],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write README.md (model card) for a model build.")
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--config", type=Path, help="training config (configs/train/*.yaml) shown under Method")
    parser.add_argument("--data", required=True, help="one or two sentences about the training data")
    parser.add_argument("--limitations", default=DEFAULT_LIMITATIONS)
    parser.add_argument("--reproduce", help="how to reproduce (default: the repo pipeline command)")
    args = parser.parse_args(argv)

    manifest_path = args.model_dir / model_manifest.MANIFEST_FILE
    if not manifest_path.is_file():
        print(f"{manifest_path} not found; run scripts/make_manifest.py first", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_manifest.parse_manifest(manifest)
    config_name = args.config.as_posix() if args.config else "configs/train/<version>.yaml"
    reproduce = args.reproduce or (
        f"See [{REPO_URL}]({REPO_URL}): `python training/pipeline.py all --config {config_name}`."
    )
    card = build_card(
        manifest, config_path=args.config, data=args.data, limitations=args.limitations, reproduce=reproduce
    )
    out = args.model_dir / "README.md"
    out.write_text(card, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
