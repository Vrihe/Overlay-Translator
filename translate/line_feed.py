"""
translate/line_feed.py — translate only the lines a region did not show last time.

A chat region re-captured by live monitoring (or by the hotkey again) still holds the
old lines above the new ones. ``new_lines()`` drops the lines already seen — exact
repeats by count, OCR-noisy repeats by similarity — so only fresh text is translated.
``RegionFeed`` keeps, per region, the last few recognised texts and the latest
translated blocks the popup shows (newest first). Everything stays in memory only.
"""

from __future__ import annotations

from collections import Counter, deque
from difflib import SequenceMatcher

# OCR of the same line can differ by a character or two between captures.
_SIMILAR = 0.85
MAX_BLOCKS = 5
# A line counts as seen if any of the last few captures had it: a line that the OCR
# misses on one capture and reads again on the next is not "new" every other time.
RECENT_CAPTURES = 4


def _norm(line: str) -> str:
    return " ".join(line.lower().split())


def new_lines(previous: str, current: str) -> str:
    """Lines of *current* not present in *previous*, in their original order."""
    old = [_norm(line) for line in previous.splitlines() if line.strip()]
    remaining = Counter(old)
    fresh: list[str] = []
    for line in current.splitlines():
        norm = _norm(line)
        if not norm:
            continue
        if remaining[norm] > 0:
            remaining[norm] -= 1  # a repeat ("gg" twice) counts once per old copy
            continue
        if norm not in remaining and any(SequenceMatcher(None, norm, o).ratio() >= _SIMILAR for o in old):
            continue
        fresh.append(line.strip())
    return "\n".join(fresh)


class RegionFeed:
    """The last recognised text of one region and its translated blocks, newest first."""

    def __init__(self) -> None:
        self._recent: deque[str] = deque(maxlen=RECENT_CAPTURES)
        self.blocks: list[tuple[str, str]] = []  # (time stamp, translated text)

    @property
    def previous_source(self) -> str | None:
        """The lines of the last RECENT_CAPTURES recognised texts (None before the first)."""
        return "\n".join(self._recent) if self._recent else None

    @previous_source.setter
    def previous_source(self, text: str) -> None:
        self._recent.append(text)

    def add(self, stamp: str, translated: str) -> None:
        self.blocks.insert(0, (stamp, translated))
        del self.blocks[MAX_BLOCKS:]
