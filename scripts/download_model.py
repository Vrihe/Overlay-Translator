"""
scripts/download_model.py — fetch the local NLLB model from the Hugging Face Hub.

Downloads the CTranslate2 int8 build into ``models/nllb-200-ct2-int8`` (the first
place the app looks for it; see ``translate/nllb_backend.py``). The repository
and revision are pinned in one place, ``config.NLLB_HF_REPO_ID`` /
``config.NLLB_HF_REVISION``, so everyone gets the same build.

The repository is public; no Hugging Face login is needed. Re-running the script
only fetches files that changed.

Usage
-----
    python scripts/download_model.py
    python scripts/download_model.py --revision v0-base
    python scripts/download_model.py --dest D:/models/nllb-200-ct2-int8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import config  # noqa: E402
from translate.nllb_backend import MODEL_DIRNAME, missing_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the local NLLB model from the Hugging Face Hub.")
    parser.add_argument("--repo-id", default=config.NLLB_HF_REPO_ID,
                        help=f"Hugging Face model repo (default: {config.NLLB_HF_REPO_ID})")
    parser.add_argument("--revision", default=config.NLLB_HF_REVISION,
                        help=f"Tag, branch or commit to download (default: {config.NLLB_HF_REVISION})")
    parser.add_argument("--dest", type=Path, default=_PROJECT_ROOT / "models" / MODEL_DIRNAME,
                        help=f"Target directory (default: models/{MODEL_DIRNAME})")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is not installed. Run: pip install huggingface_hub", file=sys.stderr)
        return 1

    print(f"Downloading {args.repo_id}@{args.revision}\n       into {args.dest}")
    path = Path(snapshot_download(
        repo_id=args.repo_id,
        revision=args.revision,
        local_dir=args.dest,
        repo_type="model",
    ))

    missing = missing_files(path)
    if missing:
        print(f"Download finished, but required files are missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    size_mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and ".cache" not in f.parts) / 2**20
    print(f"Done: {size_mb:.0f} MiB in {path}")
    if path.resolve() != (_PROJECT_ROOT / "models" / MODEL_DIRNAME).resolve():
        print("Not the default location: set this path in Settings → Бэкенд перевода → Путь к модели, "
              "or via the NLLB_MODEL_DIR environment variable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
