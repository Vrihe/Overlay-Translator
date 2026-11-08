"""Assemble the GitHub Pages site: copy landing/ into the output folder.

The landing page is plain HTML. The only build step is filling in the base URL (and the
optional Discord link), both read from landing/site.json, the one place to change when the
site moves to a custom domain.

    mkdocs build --strict -d _site/docs     # the documentation, under /docs/
    python scripts/build_site.py            # landing/ -> _site/, with the URLs filled in

    python scripts/build_site.py --print-site-url   # for the CI workflow
    python scripts/build_site.py --print-docs-url

SITE_URL in the environment overrides base_url (for a preview build).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANDING = ROOT / "landing"
TEXT_SUFFIXES = {".html", ".xml", ".txt"}
DISCORD_BLOCK = re.compile(r"[ \t]*<!--discord:start-->.*?<!--discord:end-->[ \t]*\r?\n?", re.DOTALL)
TOKEN = re.compile(r"\{\{[A-Z_]+\}\}")


def load_config() -> dict[str, str]:
    config = json.loads((LANDING / "site.json").read_text(encoding="utf-8"))
    base = os.environ.get("SITE_URL") or config["base_url"]
    return {"base_url": base.rstrip("/"), "discord_url": (config.get("discord_url") or "").strip()}


def render(text: str, config: dict[str, str]) -> str:
    if config["discord_url"]:
        text = text.replace("<!--discord:start-->", "").replace("<!--discord:end-->", "")
        text = re.sub(r"[ \t]*<!-- DISCORD PLACEHOLDER[^>]*-->\r?\n?", "", text)
        text = text.replace("{{DISCORD_URL}}", config["discord_url"])
    else:
        text = DISCORD_BLOCK.sub("", text)
    return text.replace("{{SITE_URL}}", config["base_url"])


def build(out: Path) -> int:
    config = load_config()
    count = 0
    for src in sorted(LANDING.rglob("*")):
        if not src.is_file() or src.name == "site.json":
            continue
        dest = out / src.relative_to(LANDING)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES:
            text = render(src.read_text(encoding="utf-8"), config)
            left = TOKEN.findall(text)
            if left:
                sys.exit(f"{src.relative_to(ROOT)}: unfilled placeholders {sorted(set(left))}")
            dest.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(src, dest)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "_site"), help="output folder (default: _site)")
    parser.add_argument("--print-site-url", action="store_true")
    parser.add_argument("--print-docs-url", action="store_true")
    args = parser.parse_args()

    base = load_config()["base_url"]
    if args.print_site_url:
        print(base)
    elif args.print_docs_url:
        print(base + "/docs/")
    else:
        out = Path(args.out)
        print(f"{build(out)} files -> {out} (base URL {base})")


if __name__ == "__main__":
    main()
