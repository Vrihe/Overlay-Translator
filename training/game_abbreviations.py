"""
training/game_abbreviations.py — stage 1 of the v2 fine-tune: curate
``training/game_abbreviations_en.txt`` into a lexicon and training phrases.

The source file is a glossary (``abbr | meaning | KEEP/TRANSLATE/CONTEXT | example``,
~3000 rows) where most examples are just the abbreviation itself and the policy is
a first guess. Training on it verbatim would teach the model to leave ordinary
English untranslated (``head | head | KEEP``, ``push | push | KEEP``), so every row
is resolved first:

  * meaning == abbreviation (an ordinary word): ``plain`` — translated normally,
    used as a negative example against over-expansion. Rare jargon
    (wordfreq Zipf < 3: ``gank``, ``kekw``) stays ``keep``.
  * KEEP whose spelling is a common English word (Zipf >= 4: ``a``, ``top``,
    ``black``) is dropped — the model can't tell it from the word.
  * CONTEXT: a proper-name meaning (``Discord``, ``Ground Zero``) -> keep,
    otherwise translate.
  * TRANSLATE/CONTEXT meanings with ``/`` (two meanings) or ``*`` (censored) are dropped.
  * An abbreviation that v1 (``abbr_phrases.txt``) already covers keeps v1's mode
    and expansion: v1 was validated, the new policies are a first guess.
  * Abbreviations whose rows still disagree (``lol`` = laughing / League of Legends)
    are dropped as ambiguous.

Phrases are then expanded per token with the lexicon, so a chat line mixing both
kinds (``lf healer for dungeon, inv pls``) gets the right "full" version and keep terms.

Phrases per lexicon entry: the real examples, the abbreviation alone, and two chat
wrappers (``guys, idk``; one in upper case). Section 13 template sentences go to
test; ~20 % of the real examples go to test and ~10 % to val (their abbreviation
stays in train through the other phrases). Train phrases get 3 random target
languages, val/test phrases and plain negatives all 9.

Output (``data/interim/v2/``):
  lexicon.json          abbr -> {mode, expansion, source}
  game_phrases.jsonl    {short, full, keep_terms, expanded, mode, origin, split, langs}
  curation_report.json  dropped rows with the reason

and the app glossary ``translate/glossary/game_en.json`` (``translate/chat_glossary.py``):
every lexicon term -> the English meaning NLLB translates instead of the term, or
``null`` = protect the term verbatim (proper names: ``Valorant``, ``ACOG``; ambiguous:
``tw`` = Taiwan / Twitch / team wipe). Ordinary words (``plain``) are not in it.

Usage
-----
    .venv\\Scripts\\python training/game_abbreviations.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wordfreq import zipf_frequency

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abbr_phrases import load_phrases  # noqa: E402
from translate_phrases import LANGS  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_TXT = Path(__file__).resolve().parent / "game_abbreviations_en.txt"
OUT_DIR = _PROJECT_ROOT / "data" / "interim" / "v2"
APP_GLOSSARY = _PROJECT_ROOT / "translate" / "glossary" / "game_en.json"
GLOSSARY_VERSION = 2
# Meanings that read better in a translated chat line than the literal expansion.
APP_MEANING_OVERRIDE = {"rng": "luck", "lol": "haha", "xd": "haha", "gank": "ambush", "rngesus": "luck",
                        # two meanings in the glossary; the chat reading is far more common
                        "inv": "invite", "lf": "looking for", "pog": "awesome", "poggers": "awesome",
                        "kekw": "haha", "lul": "haha", "lulw": "haha", "omegalul": "haha",
                        # trade / group ads: without a subject NLLB writes «Хотите продать», «Вы ищете»
                        "wts": "I want to sell", "wtb": "I want to buy", "wtt": "I want to trade",
                        "lfg": "I'm looking for a group", "lfm": "we need more players",
                        # "overpowered" comes out as «одержимы победой»
                        "op": "too strong"}

SEED = 42
PLAIN_ZIPF = 3.0          # meaning == abbr and at least this common -> ordinary word
COMMON_ZIPF = 4.0         # KEEP abbreviation this common -> indistinguishable from the word
TRAIN_LANGS = 3           # target languages per train phrase
# Plain negatives get every language: with 3 the v2 run left ordinary words untranslated
# (83 of 513 test words copied verbatim vs 53 for v0-base).
PLAIN_TRAIN_LANGS = 9
EXAMPLE_TEST, EXAMPLE_VAL = 0.20, 0.10
PLAIN_TEST, PLAIN_VAL = 0.10, 0.05
MAX_PLAIN = 600           # plain negatives are a regulariser, not the task

# Common-word spellings that are still standard game abbreviations in chat.
COMMON_KEEP_ALLOW = {"op", "hp", "mp", "ap", "ad", "cc", "cd", "dps", "ah", "mvp", "aoe", "pve", "pvp",
                     "dm", "eu", "na", "bis", "ms", "ar", "smg", "mg", "dot", "hot", "los", "k/d"}
# Single letters are only usable as a whole utterance ("F", "W") or with a number ("100g");
# as a token inside a phrase "a", "e", "s" are ordinary words.
SINGLE_TRANSLATE_ALLOW = {"u", "r", "y", "k"}
# CONTEXT rows are only resolved in the social/chat section (ez, rip, mid); elsewhere the
# meaning is game-specific (creep = creep tumor, all = alliance) and expanding it is wrong.
SOCIAL_SECTION = 1
# TRANSLATE rows that are ordinary words with a narrower meaning in the glossary.
TRANSLATE_DENY = {"all", "firm", "fixed", "neck", "duo", "trio", "quad", "pro", "pros", "admin",
                  "app", "apps", "whisper"}
# Chat writes "2 min", "30 sec": the plural is the usual reading.
EXPANSION_OVERRIDE = {"min": "minutes", "sec": "seconds"}
NUMBER_SUFFIXES = {"g", "gp", "k", "kk", "m", "b", "cr", "c", "s", "sp", "cp", "pp", "mil", "mill"}
WRAPPERS = ["{x}, guys", "guys, {x}", "ok, {x}", "{x}, ok?", "hey, {x}", "{x}, team", "yeah, {x}", "{x}!"]
STRIP = ",.!?;:\"'()"


def parse_source(path: Path = SOURCE_TXT) -> tuple[list[dict], list[str]]:
    """Glossary rows and the section-13 template sentences."""
    rows, templates, section = [], [], 0
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("## "):
            section = int(line[3:].split(".")[0])
            continue
        if not line or line[0] in "#=":
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 4:
            rows.append({"line": lineno, "section": section, "abbr": parts[0], "meaning": parts[1],
                         "policy": parts[2], "example": parts[3]})
        elif len(parts) == 1:
            templates.append(line)
        else:
            raise ValueError(f"{path.name}:{lineno}: expected 4 fields: {line}")
    return rows, templates


def resolve_row(row: dict) -> tuple[str | None, str]:
    """(mode, reason): mode is keep / translate / plain, or None with the reason it was dropped."""
    abbr, meaning, policy = row["abbr"].lower(), row["meaning"], row["policy"]
    # wordfreq splits "m+", "+10", "k/d" into common pieces; a spelling with symbols or digits is no word
    zipf = zipf_frequency(abbr, "en") if abbr.isalpha() else 0.0
    if policy == "CONTEXT":
        if any(c.isupper() for c in meaning):
            policy = "KEEP"
        elif row["section"] == SOCIAL_SECTION:
            policy = "TRANSLATE"
        else:
            return None, "context-dependent meaning"
    if abbr in TRANSLATE_DENY:
        return None, "expansion changes the meaning"
    if abbr == meaning.lower():
        return ("plain" if policy == "TRANSLATE" or zipf >= PLAIN_ZIPF else "keep"), "meaning == abbreviation"
    if policy == "TRANSLATE":
        if "/" in meaning:
            return None, "two meanings"
        if "*" in meaning:
            return None, "censored meaning"
        if len(abbr) == 1 and abbr not in SINGLE_TRANSLATE_ALLOW:
            return None, "single letter"
        return "translate", ""
    if zipf >= COMMON_ZIPF and abbr not in COMMON_KEEP_ALLOW:
        return None, f"common English word (Zipf {zipf:.1f})"
    return "keep", ""


def build_lexicon(rows: list[dict], v1: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    lexicon: dict[str, dict] = {}
    for p in v1:
        lexicon[p["abbr"].lower()] = {"mode": p["mode"], "expansion": p["expansion"], "source": "v1"}

    dropped: list[dict] = []
    candidates: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for row in rows:
        if " " in row["abbr"]:
            continue  # multi-word rows are phrases, their tokens are looked up individually
        mode, reason = resolve_row(row)
        if mode is None:
            dropped.append({**row, "reason": reason})
            continue
        row["mode"] = mode
        candidates[row["abbr"].lower()].append((mode, row["meaning"].lower().strip(), row))

    for abbr, cands in candidates.items():
        if abbr in lexicon:
            continue  # v1 wins
        modes = {m for m, _, _ in cands}
        meanings = {e for m, e, _ in cands if m == "translate"}
        if len(modes) > 1 or len(meanings) > 1:
            for _, _, row in cands:
                dropped.append({**row, "reason": f"ambiguous: {sorted(modes)} {sorted(meanings)}"})
            continue
        mode = modes.pop()
        expansion = EXPANSION_OVERRIDE.get(abbr, cands[0][2]["meaning"]) if mode == "translate" else None
        lexicon[abbr] = {"mode": mode, "expansion": expansion,
                         "source": "v2", "rows": [r["line"] for _, _, r in cands]}
    return lexicon, dropped


def lookup(token: str, lexicon: dict[str, dict]) -> tuple[str, dict] | None:
    """Match a whitespace token against the lexicon: (matched text, entry)."""
    low = token.lower()
    for cand in (low, low.strip(STRIP), low.rstrip(STRIP)):
        entry = lexicon.get(cand)
        if entry and (len(cand) > 1 or entry["mode"] == "translate"):
            start = low.find(cand)
            return token[start:start + len(cand)], entry
    num = re.fullmatch(r"[+]?\d+(?:[.,]\d+)?([a-z]+)", low.strip(STRIP))
    if num and num.group(1) in NUMBER_SUFFIXES:
        core = token.strip(STRIP)
        return core, {"mode": "keep", "expansion": None}
    return None


def analyse(short: str, lexicon: dict[str, dict], own: tuple[str, dict] | None = None) -> dict:
    """Expand translate abbreviations, collect keep terms. ``own`` forces the row's abbreviation."""
    out_tokens, keep_terms, expanded = [], [], []
    for token in short.split():
        hit = None
        if own is not None and token.lower().strip(STRIP) == own[0]:
            start = token.lower().find(own[0])
            hit = token[start:start + len(own[0])], own[1]
        hit = hit or lookup(token, lexicon)
        if hit is None or hit[1]["mode"] == "plain":
            out_tokens.append(token)
            continue
        text, entry = hit
        if entry["mode"] == "keep":
            keep_terms.append(text)
            out_tokens.append(token)
        else:
            expanded.append(text.lower())
            out_tokens.append(token.replace(text, entry["expansion"], 1))
    full = " ".join(out_tokens)
    if full and short[:1].isupper() and expanded:
        full = full[0].upper() + full[1:]
    mode = "translate" if expanded else "keep" if keep_terms else "plain"
    return {"full": full, "keep_terms": sorted(set(keep_terms), key=str.lower), "expanded": expanded,
            "mode": mode}


def app_glossary(rows: list[dict], lexicon: dict[str, dict]) -> dict[str, str | None]:
    """term -> English meaning to translate instead, or None to keep the term verbatim."""
    meanings: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        meanings[r["abbr"].lower()].add(re.sub(r"\s*\(.*?\)", "", r["meaning"]).strip())
    out: dict[str, str | None] = {}
    for term, entry in sorted(lexicon.items()):
        if entry["mode"] == "plain":
            continue
        if term in APP_MEANING_OVERRIDE:
            out[term] = APP_MEANING_OVERRIDE[term]
        elif entry["expansion"]:  # translate entries and v1 keep entries
            out[term] = entry["expansion"]
        else:
            found = meanings.get(term, set())
            meaning = next(iter(found)) if len(found) == 1 else ""
            usable = (meaning and meaning.lower() != term and "/" not in meaning
                      and not any(c.isupper() for c in meaning))
            out[term] = meaning if usable else None
    return out


def main() -> int:
    rng = random.Random(SEED)
    rows, templates = parse_source()
    v1 = load_phrases()
    lexicon, dropped = build_lexicon(rows, v1)

    # v1 phrases are already in v1 train/val/test with their own split: a v2 copy would leak
    # a v1 test phrase into train or make a v1 train phrase a v2 test item.
    v1_phrases = {p["short"].lower() for p in v1}

    phrases: dict[str, dict] = {}  # lowercase short -> phrase; first assignment wins, test before train

    def add(short: str, origin: str, split: str, own: tuple[str, dict] | None = None) -> None:
        key = short.lower()
        if key in phrases or not short.strip():
            return
        if key in v1_phrases:
            return
        info = analyse(short, lexicon, own)
        if info["mode"] == "plain" and origin != "plain":
            return  # no lexicon token survived curation
        phrases[key] = {"short": short, **info, "origin": origin, "split": split}

    # 1. section-13 template sentences: unseen mixed chat lines -> test
    for t in templates:
        add(t, "template", "test")

    # 2. real examples: ~20 % test, ~10 % val, rest train
    examples = [r for r in rows if r["example"].lower() != r["abbr"].lower()]
    rng.shuffle(examples)
    plain_rows = []
    for r in examples:
        entry = lexicon.get(r["abbr"].lower())
        if entry is None and " " not in r["abbr"]:
            continue  # dropped abbreviation
        if entry is not None and entry["mode"] == "plain":
            plain_rows.append(r)
            continue
        own = (r["abbr"].lower(), entry) if entry else None
        x = rng.random()
        add(r["example"], "example", "test" if x < EXAMPLE_TEST else "val" if x < EXAMPLE_TEST + EXAMPLE_VAL
            else "train", own)

    # 3. every v2 lexicon entry alone and in two chat wrappers -> train
    for abbr in sorted(a for a, e in lexicon.items() if e["source"] == "v2" and e["mode"] != "plain"):
        entry = lexicon[abbr]
        alone = next((r["example"] for r in rows if r["abbr"].lower() == abbr
                      and r["example"].lower() == abbr), abbr)
        own = (abbr, entry)
        add(alone, "alone", "train", own)
        upper = abbr.isalpha() and len(abbr) <= 5 and rng.random() < 0.5
        for i, tpl in enumerate(rng.sample(WRAPPERS, 2)):
            add(tpl.format(x=abbr.upper() if upper and i == 0 else alone), "wrapper", "train", own)

    # 4. plain negatives: ordinary words should still translate normally
    plain_src = [r["example"] for r in plain_rows] + sorted(
        {r["example"] for r in rows if r["example"].lower() == r["abbr"].lower()
         and lexicon.get(r["abbr"].lower(), {}).get("mode") == "plain"})
    rng.shuffle(plain_src)
    for s in plain_src[:MAX_PLAIN]:
        x = rng.random()
        add(s, "plain", "test" if x < PLAIN_TEST else "val" if x < PLAIN_TEST + PLAIN_VAL else "train")

    langs = list(LANGS)
    for key, p in phrases.items():
        # seeded by the phrase itself, so adding or removing phrases never reshuffles the others
        n_langs = PLAIN_TRAIN_LANGS if p["mode"] == "plain" else TRAIN_LANGS
        p["langs"] = (sorted(random.Random(f"{SEED}:{key}").sample(langs, n_langs))
                      if p["split"] == "train" and n_langs < len(langs) else langs)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "lexicon.json").write_text(json.dumps(lexicon, indent=1, ensure_ascii=False), encoding="utf-8")
    glossary = app_glossary(rows, lexicon)
    APP_GLOSSARY.parent.mkdir(parents=True, exist_ok=True)
    APP_GLOSSARY.write_text(json.dumps({"version": GLOSSARY_VERSION, "source_lang": "en", "terms": glossary},
                                       indent=0, ensure_ascii=False), encoding="utf-8")
    with (OUT_DIR / "game_phrases.jsonl").open("w", encoding="utf-8") as f:
        for p in phrases.values():
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    reasons = Counter(d["reason"].split(":")[0].split(" (")[0] for d in dropped)
    (OUT_DIR / "curation_report.json").write_text(json.dumps(
        {"rows": len(rows), "templates": len(templates), "dropped_by_reason": reasons,
         "dropped": [{k: d[k] for k in ("line", "abbr", "meaning", "policy", "reason")} for d in dropped]},
        indent=1, ensure_ascii=False), encoding="utf-8")

    lex_modes = Counter((e["source"], e["mode"]) for e in lexicon.values())
    print(f"Rows: {len(rows)} glossary + {len(templates)} templates")
    print(f"Lexicon: {len(lexicon)} entries {dict(lex_modes)}")
    print(f"Dropped rows: {len(dropped)} {dict(reasons)}")
    split_mode = Counter((p["split"], p["mode"]) for p in phrases.values())
    print(f"Phrases: {len(phrases)} {dict(sorted(split_mode.items()))}")
    print(f"Pairs to translate: {sum(len(p['langs']) for p in phrases.values())}")
    print(f"Saved to {OUT_DIR.relative_to(_PROJECT_ROOT)}")
    print(f"App glossary: {sum(v is not None for v in glossary.values())} expanded, "
          f"{sum(v is None for v in glossary.values())} protected -> {APP_GLOSSARY.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
