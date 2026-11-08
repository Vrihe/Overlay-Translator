"""Check the assembled site (default: _site): every internal link, image, script and stylesheet
of the landing pages must resolve to a file, in-page anchors must exist, and each page must
have one h1, a title, a description and a canonical URL. External links are not fetched.

    python scripts/check_site.py [_site]

Exit code 1 when something is broken.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "download.html", "ru/index.html", "ru/download.html"]
REF_ATTRS = {"a": "href", "link": "href", "img": "src", "script": "src", "source": "src"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.h1 = 0
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1 += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"]] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href", "")
        attr = REF_ATTRS.get(tag)
        if attr and a.get(attr):
            self.refs.append((tag, a[attr]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def resolve(site: Path, page: Path, ref: str) -> Path | None:
    """Map an internal reference to the file a web server would serve, or None if it is missing."""
    path = unquote(urlparse(ref).path)
    target = site / path.lstrip("/") if path.startswith("/") else (page.parent / path)
    target = target.resolve()
    if target.is_dir():
        target = target / "index.html"
    return target if target.is_file() else None


def parse(path: Path) -> Page:
    parser = Page()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site").resolve()
    problems: list[str] = []
    checked = 0
    titles: dict[str, str] = {}
    descriptions: dict[str, str] = {}

    for name in PAGES:
        page_path = site / name
        if not page_path.is_file():
            problems.append(f"{name}: page is missing")
            continue
        page = parse(page_path)
        if page.h1 != 1:
            problems.append(f"{name}: {page.h1} h1 elements, expected 1")
        title, desc = page.title.strip(), page.meta.get("description", "")
        if not title or not desc or not page.canonical:
            problems.append(f"{name}: missing title, description or canonical")
        for value, seen, what in ((title, titles, "title"), (desc, descriptions, "description")):
            if value in seen:
                problems.append(f"{name}: same {what} as {seen[value]}")
            seen[value] = name
        for tag, ref in page.refs:
            parsed = urlparse(ref)
            if parsed.scheme or ref.startswith(("mailto:", "//")):
                continue
            checked += 1
            base_ref, fragment = urldefrag(ref)
            target = resolve(site, page_path, base_ref) if base_ref else page_path
            if target is None:
                problems.append(f"{name}: <{tag}> {ref} does not exist")
            elif fragment and target.suffix == ".html":
                ids = page.ids if target == page_path else parse(target).ids
                if fragment not in ids:
                    problems.append(f"{name}: {ref} anchor not found")

    for name in ("sitemap.xml", "robots.txt", "img/og-image.png"):
        if not (site / name).is_file():
            problems.append(f"{name}: missing")
    robots = site / "robots.txt"
    if robots.is_file() and "Sitemap:" not in robots.read_text(encoding="utf-8"):
        problems.append("robots.txt: no Sitemap line")

    print(f"checked {checked} internal references on {len(PAGES)} pages in {site}")
    for p in problems:
        print("  PROBLEM:", p)
    if not problems:
        print("OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
