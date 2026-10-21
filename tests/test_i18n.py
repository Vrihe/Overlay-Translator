"""
tests/test_i18n.py — interface language: lookup, placeholders, catalog completeness.

Scans the app sources for ``tr("…")`` / ``N_("…")`` literals and checks that the
English catalog covers every one of them with the same ``{placeholders}``.
"""

import ast
import os
import string
import unittest
from pathlib import Path
from unittest import mock

import i18n
from i18n import N_, resolve_language, set_language, tr
from i18n.en import MESSAGES

ROOT = Path(__file__).resolve().parent.parent
# Offline utilities are not part of the app and are not translated.
_SKIP_DIRS = {"tests", "training", "scripts", ".venv", "build", "dist", "_build_cache"}


def _source_files() -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Prune in place so .venv and friends are never walked.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        files += [Path(dirpath) / f for f in filenames if f.endswith(".py")]
    return files


def _marked_strings() -> dict[str, str]:
    """Every literal passed to tr() / N_() → the file it first appears in."""
    found: dict[str, str] = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in ("tr", "N_")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.setdefault(node.args[0].value, str(path.relative_to(ROOT)))
    return found


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


class TestCatalog(unittest.TestCase):
    def test_every_marked_string_has_an_english_entry(self):
        missing = {k: f for k, f in _marked_strings().items() if k not in MESSAGES}
        self.assertEqual(missing, {}, "add these to i18n/en.py")

    def test_placeholders_match(self):
        bad = {k: v for k, v in MESSAGES.items() if _placeholders(k) != _placeholders(v)}
        self.assertEqual(bad, {})

    def test_no_unused_entries(self):
        unused = set(MESSAGES) - set(_marked_strings())
        self.assertEqual(unused, set(), "remove stale entries from i18n/en.py")

    def test_no_duplicate_keys(self):
        tree = ast.parse((ROOT / "i18n" / "en.py").read_text(encoding="utf-8"))
        keys = [
            k.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for k in node.keys
            if isinstance(k, ast.Constant)
        ]
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(dupes, set())


class TestTr(unittest.TestCase):
    def tearDown(self):
        set_language(None)

    def test_russian_returns_source(self):
        set_language("ru")
        self.assertEqual(tr("Перевести"), "Перевести")

    def test_english_looks_up_catalog(self):
        set_language("en")
        self.assertEqual(tr("Перевести"), "Translate")

    def test_placeholders_filled_after_lookup(self):
        set_language("en")
        self.assertEqual(tr("Ошибка: {error}", error="boom"), "Error: boom")
        set_language("ru")
        self.assertEqual(tr("Ошибка: {error}", error="boom"), "Ошибка: boom")

    def test_missing_entry_falls_back_to_source(self):
        set_language("en")
        self.assertEqual(tr("Нет такой строки"), "Нет такой строки")

    def test_values_with_braces_are_not_reformatted(self):
        set_language("en")
        self.assertEqual(tr("Ошибка: {error}", error="{x}"), "Error: {x}")

    def test_n_marks_without_translating(self):
        set_language("en")
        self.assertEqual(N_("Перевести"), "Перевести")


class TestResolveLanguage(unittest.TestCase):
    def test_explicit_values(self):
        self.assertEqual(resolve_language("ru"), "ru")
        self.assertEqual(resolve_language("en"), "en")

    def test_auto_follows_system_language(self):
        for system, expected in [("ru", "ru"), ("uk", "ru"), ("be", "ru"), ("de", "en"), ("", "en")]:
            with mock.patch.object(i18n, "_system_language", return_value=system):
                self.assertEqual(resolve_language("auto"), expected, system)
                self.assertEqual(resolve_language(None), expected, system)
                self.assertEqual(resolve_language("xx"), expected, system)


if __name__ == "__main__":
    unittest.main()
