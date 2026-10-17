"""
translate/chat_glossary.py — game-chat glossary for the local NLLB backend.

NLLB does not know chat slang: ``wts`` / ``gg wp`` / ``idk`` get dropped,
transliterated or invented ("gg ez" -> «Доброе утро»). Before translation every
known term in an English line is replaced with its plain-English meaning, so the
model translates the meaning instead of guessing:

    wts leather armor, pm me  ->  want to sell leather armor, private message me
    lf2m for dungeon          ->  we need 2 more players for dungeon

Terms without a translatable meaning (game titles, weapons, emotes, ambiguous
spellings) are masked as ``[1]``, ``[2]`` ... — NLLB copies those verbatim — and put
back after translation in their original spelling.

The term list is ``translate/glossary/game_en.json``, exported by
``training/game_abbreviations.py`` from the curated v2 lexicon (ordinary words and
ambiguous abbreviations are already filtered out there).

Usage (see ``NllbBackend._translate_text``)::

    prepared = prepare(text)
    out = restore(model(prepared.text), prepared)
    if out is None:                      # the model lost a placeholder
        out = model(prepared.unmasked)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_logger = logging.getLogger(__name__)

GLOSSARY_PATH = Path(__file__).resolve().parent / "glossary" / "game_en.json"

_STRIP = ",.!?;:\"'()"
# Prices like "500g", "2kk", "10k": only suffixes with a single reading in chat
# ("2m" may be minutes, "10s" seconds).
_NUMBER_SUFFIXES = {"g": "gold", "gp": "gold", "k": "thousand", "kk": "million",
                    "mil": "million", "mill": "million", "cr": "credits"}
_NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)([a-z]+)")
_LF_N_MORE_RE = re.compile(r"lf(\d+)m")  # lf1m, lf2m, lf3m ... = looking for N more


@dataclass
class Prepared:
    text: str                                   # what the model translates (terms masked as [n])
    unmasked: str                               # same, with protected terms left as they are
    restore: dict[str, str] = field(default_factory=dict)  # "[n]" -> original spelling
    expanded: list[str] = field(default_factory=list)      # terms replaced by their meaning

    @property
    def changed(self) -> bool:
        return bool(self.restore or self.expanded)


@lru_cache(maxsize=1)
def load_terms(path: Path = GLOSSARY_PATH) -> dict[str, str | None]:
    """term (lowercase) -> English meaning, or None = keep the term verbatim."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _logger.warning("Chat glossary not found: %s", path)
        return {}
    return data["terms"]


def glossary_version(path: Path = GLOSSARY_PATH) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("version", 0))
    except (FileNotFoundError, ValueError):
        return 0


def _lookup(core: str, terms: dict[str, str | None]) -> tuple[bool, str | None]:
    """(known, meaning) for a token stripped of surrounding punctuation."""
    low = core.lower()
    # before the term list: it has some lfNm spellings with a subject-less meaning
    if m := _LF_N_MORE_RE.fullmatch(low):
        return True, f"we need {m.group(1)} more players"
    if low in terms:
        return True, terms[low]
    if (m := _NUMBER_RE.fullmatch(low)) and m.group(2) in _NUMBER_SUFFIXES:
        return True, f"{m.group(1)} {_NUMBER_SUFFIXES[m.group(2)]}"
    return False, None


def prepare(text: str, terms: dict[str, str | None] | None = None) -> Prepared:
    """Expand known chat terms in an English line; mask the ones to keep verbatim."""
    terms = load_terms() if terms is None else terms
    masked, unmasked, restore, expanded = [], [], {}, []
    # Split on whitespace but keep it: OCR lines are joined with "\n".
    for i, token in enumerate(re.split(r"(\s+)", text)):
        core = token.strip(_STRIP)
        known, meaning = _lookup(core, terms) if core and not token.isspace() else (False, None)
        if not known:
            masked.append(token)
            unmasked.append(token)
            continue
        start = token.find(core)
        head, tail = token[:start], token[start + len(core):]
        if meaning is None:
            placeholder = f"[{len(restore) + 1}]"
            restore[placeholder] = core
            masked.append(head + placeholder + tail)
            unmasked.append(token)
        else:
            if i == 0 and core[:1].isupper():
                meaning = meaning[:1].upper() + meaning[1:]
            expanded.append(core.lower())
            masked.append(head + meaning + tail)
            unmasked.append(head + meaning + tail)
    return Prepared("".join(masked), "".join(unmasked), restore, expanded)


def restore(translation: str, prepared: Prepared) -> str | None:
    """Put protected terms back; None if the model dropped any placeholder."""
    if not all(ph in translation for ph in prepared.restore):
        return None
    for placeholder, original in prepared.restore.items():
        translation = translation.replace(placeholder, original)
    return translation
