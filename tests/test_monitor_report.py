"""
tests/test_monitor_report.py — the model monitoring report (scripts/monitor_report.py).

Covers the unknown-token heuristic, lost keep terms, the drift verdict, the privacy default
(no tokens printed) and the CLI exit codes. All rows are synthetic and the history DB is a
temporary SQLite file.
"""

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("monitor_report", _ROOT / "scripts" / "monitor_report.py")
mr = importlib.util.module_from_spec(_spec)
sys.modules["monitor_report"] = mr
_spec.loader.exec_module(mr)

GLOSSARY = {"gg", "lfm", "pm"}
KEEP = {"gg", "pm"}
DAY = 86400
NOW = 1_000_000_000.0


def _row(src, tgt="x", domain="general|nllb", age_days=0.0):
    return {"source_text": src, "translated_text": tgt, "domain_id": domain, "timestamp": NOW - age_days * DAY}


class TestUnknown(unittest.TestCase):
    def test_glossary_vocab_and_ordinary_words_are_known(self):
        self.assertFalse(mr.is_unknown("gg", GLOSSARY))
        self.assertFalse(mr.is_unknown("heal", GLOSSARY))
        self.assertFalse(mr.is_unknown("wtb", GLOSSARY, vocab={"wtb"}))

    def test_slang_shapes_are_unknown(self):
        self.assertTrue(mr.is_unknown("lf5m", GLOSSARY))
        self.assertTrue(mr.is_unknown("wtb", GLOSSARY))
        self.assertFalse(mr.is_unknown("+10", GLOSSARY))  # no letters

    def test_unknown_tokens_of_a_line(self):
        self.assertEqual(mr.unknown_tokens("LFM gg need lf5m wtb", GLOSSARY), ["lf5m", "wtb"])


class TestLostKeep(unittest.TestCase):
    def test_reports_only_missing_whole_words(self):
        self.assertEqual(mr.lost_keep_terms("gg pm me", "хорошая игра, пиши в pm", KEEP), ["gg"])
        self.assertEqual(mr.lost_keep_terms("pmx", "x", KEEP), [])  # not a whole word
        self.assertEqual(mr.lost_keep_terms("GG", "gg", KEEP), [])  # case-insensitive


class TestDrift(unittest.TestCase):
    def _rows(self, recent_unknown, earlier_unknown, n=60):
        rows = []
        for i in range(n):
            rows.append(_row("wtb now" if i < recent_unknown else "hello there", age_days=1))
            rows.append(_row("wtb now" if i < earlier_unknown else "hello there", age_days=100))
        return rows

    def test_growth_above_threshold_is_drift(self):
        result = mr.drift(self._rows(30, 5), GLOSSARY, now=NOW, window_days=30)
        self.assertTrue(result["drift"])
        self.assertGreater(result["delta_points"], mr.DEFAULT_DRIFT_POINTS)

    def test_stable_share_is_no_drift(self):
        self.assertFalse(mr.drift(self._rows(10, 10), GLOSSARY, now=NOW, window_days=30)["drift"])

    def test_too_few_rows_never_flags_drift(self):
        result = mr.drift(self._rows(5, 0, n=5), GLOSSARY, now=NOW, window_days=30)
        self.assertFalse(result["enough_data"])
        self.assertFalse(result["drift"])


class TestReport(unittest.TestCase):
    def test_only_offline_rows_and_tokens_hidden_by_default(self):
        rows = [_row("gg wtb", "x"), _row("gg", "y", domain="general"), _row("hello", "hi")]
        report = mr.build_report(rows, GLOSSARY, KEEP, now=NOW)
        self.assertEqual(report["rows"], 2)
        self.assertEqual(report["lost_keep_terms"], [("gg", 1)])
        self.assertNotIn("top_unknown_tokens", report)
        self.assertNotIn("wtb", mr.format_report(report))
        shown = mr.build_report(rows, GLOSSARY, KEEP, now=NOW, show_tokens=True)
        self.assertEqual(shown["top_unknown_tokens"], [("wtb", 1)])


class TestCli(unittest.TestCase):
    def _db(self, tmp, rows):
        path = Path(tmp) / "translations.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE translations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_text TEXT, source_lang TEXT,"
            " target_lang TEXT, domain_id TEXT, translated_text TEXT, timestamp REAL)"
        )
        conn.executemany(
            "INSERT INTO translations (source_text, source_lang, target_lang, domain_id, translated_text, timestamp)"
            " VALUES (?, 'en', 'ru', ?, ?, ?)",
            [(r["source_text"], r["domain_id"], r["translated_text"], r["timestamp"]) for r in rows],
        )
        conn.commit()
        conn.close()
        return path

    def test_missing_db_is_an_error(self):
        self.assertEqual(mr.main(["--db", str(Path(tempfile.gettempdir()) / "no-such-history.db")]), 1)

    def test_writes_json_and_returns_zero_without_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp, [_row("gg", "x", age_days=-1)])
            out = Path(tmp) / "r.json"
            self.assertEqual(mr.main(["--db", str(db), "--json", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["rows"], 1)


if __name__ == "__main__":
    unittest.main()
