"""
tests/test_quality_gate.py — the model quality gate (training/quality_gate.py).

Pure logic on score dicts: every check, a missing metric failing its check, the report, and the
CLI exit codes. No models, no network.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_TRAINING = str(Path(__file__).resolve().parent.parent / "training")
if _TRAINING not in sys.path:
    sys.path.insert(0, _TRAINING)

import quality_gate as qg  # noqa: E402

TH = qg.load_thresholds()


def _system(**over):
    base = {
        "rows": 400,
        "chrf": 55.0,
        "chrf_by_category": {"ordinary": 60.0},
        "keep_rate": 95.0,
        "wrong_expansion_rate": 4.0,
        "ocr_noise": {"drop": 5.0},
    }
    base.update(over)
    return base


def _result(candidate, baseline=None):
    checks = qg.evaluate_gate(candidate, baseline or _system(), TH)
    return checks, {c.name: c.passed for c in checks}


class TestChecks(unittest.TestCase):
    def test_shipped_thresholds_are_complete(self):
        self.assertEqual(set(TH), set(qg.REQUIRED_KEYS))

    def test_equal_candidate_passes(self):
        checks, _ = _result(_system())
        self.assertTrue(qg.passed(checks))

    def test_each_check_can_fail_alone(self):
        cases = {
            "rows": _system(rows=299),
            "keep rate": _system(keep_rate=89.9),
            "overall chrF": _system(chrf=53.9),
            "ordinary-word chrF": _system(chrf_by_category={"ordinary": 57.9}),
            "wrong expansions": _system(wrong_expansion_rate=10.1),
            "OCR noise": _system(ocr_noise={"drop": 8.1}),
        }
        for name, candidate in cases.items():
            with self.subTest(check=name):
                checks, by_name = _result(candidate)
                self.assertFalse(by_name[name])
                self.assertEqual([n for n, ok in by_name.items() if not ok], [name])
                self.assertFalse(qg.passed(checks))

    def test_values_at_the_threshold_pass(self):
        checks, _ = _result(
            _system(
                rows=300,
                keep_rate=90.0,
                chrf=54.0,
                chrf_by_category={"ordinary": 58.0},
                wrong_expansion_rate=10.0,
                ocr_noise={"drop": 8.0},
            )
        )
        self.assertTrue(qg.passed(checks))

    def test_improvement_passes(self):
        checks, _ = _result(_system(chrf=60.0, keep_rate=99.0, ocr_noise={"drop": 1.0}))
        self.assertTrue(qg.passed(checks))

    def test_missing_metric_fails_its_check(self):
        _, by_name = _result(_system(wrong_expansion_rate=None, ocr_noise=None))
        self.assertFalse(by_name["wrong expansions"])
        self.assertFalse(by_name["OCR noise"])
        _, by_name = _result(_system(), _system(chrf_by_category={}))
        self.assertFalse(by_name["ordinary-word chrF"])

    def test_empty_check_list_never_passes(self):
        self.assertFalse(qg.passed([]))

    def test_bad_thresholds_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_text(json.dumps({"min_rows": 1}))
            with self.assertRaises(ValueError):
                qg.load_thresholds(path)


class TestReportAndCli(unittest.TestCase):
    def _run(self, systems, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.json"
            summary.write_text(json.dumps({"gold_sha256": "f" * 64, "systems": systems}))
            report = Path(tmp) / "out" / "gate.md"
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = qg.main([str(summary), "--candidate", "v3", "--baseline", "v2", "--report", str(report), *extra])
            return code, out.getvalue(), report.read_text(encoding="utf-8") if report.exists() else None

    def test_pass_writes_report(self):
        code, out, report = self._run({"v3": _system(), "v2": _system()})
        self.assertEqual(code, 0)
        self.assertIn("PASSED", report)
        self.assertIn("f" * 64, report)
        self.assertEqual(out.strip(), report.strip())

    def test_fail_exit_code_and_marked_row(self):
        code, _, report = self._run({"v3": _system(keep_rate=50.0), "v2": _system()})
        self.assertEqual(code, 1)
        self.assertIn("FAILED", report)
        self.assertIn("**FAIL**", report)

    def test_unknown_system_is_an_error(self):
        code, _, report = self._run({"v2": _system()})
        self.assertEqual(code, 2)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
