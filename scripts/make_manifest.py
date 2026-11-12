"""
scripts/make_manifest.py — write ``manifest.json`` for a CTranslate2 build before uploading it to the Hub.

Usage
-----
    python scripts/make_manifest.py models/nllb-200-ct2-int8 --version v2-game \\
        --min-app-version 1.4.0 --channel stable --metrics checkpoints/eval/summary.json:v2-game

``--metrics FILE:SYSTEM`` copies the numbers of one system from an ``evaluate.py`` /
``gold_eval.py`` summary (numbers only, no text). Upload the resulting ``manifest.json`` with the
build and create the tag afterwards, so the manifest is part of the tagged commit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from translate import model_manifest  # noqa: E402


def _numbers(summary_path: Path, system: str) -> dict[str, float]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    try:
        result = summary["systems"][system]
    except KeyError:
        raise SystemExit(f"no system {system!r} in {summary_path}") from None
    flat: dict[str, float] = {}

    def walk(node: dict, prefix: str = "") -> None:
        for key, value in node.items():
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                walk(value, name)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                flat[name] = value

    walk({k: v for k, v in result.items() if k != "spec"})
    return flat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write manifest.json for a model build.")
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--version", required=True, help="tag of this build, e.g. v2-game")
    parser.add_argument("--min-app-version", default="0.0.0")
    parser.add_argument("--channel", choices=model_manifest.CHANNELS, default="stable")
    parser.add_argument("--metrics", help="SUMMARY.json:SYSTEM to copy numbers from")
    args = parser.parse_args(argv)

    if not args.model_dir.is_dir():
        print(f"not a directory: {args.model_dir}", file=sys.stderr)
        return 1
    metrics = {}
    if args.metrics:
        path, _, system = args.metrics.rpartition(":")
        metrics = _numbers(Path(path), system)
    data = model_manifest.build_manifest(
        args.model_dir, args.version, metrics=metrics, min_app_version=args.min_app_version, channel=args.channel
    )
    out = args.model_dir / model_manifest.MANIFEST_FILE
    out.write_text(model_manifest.dumps(data), encoding="utf-8")
    print(f"Wrote {out} ({len(data['files'])} files, channel {args.channel})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
