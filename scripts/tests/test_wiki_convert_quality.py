"""Tests for the KR-R2 parse-quality gate in
scripts/wiki_convert.py (Marathon Round 3, lane TA4): a good
parse scores high, empty/garbled/repetitive parses score low,
the score is recorded in the ingest report, a caller-set
threshold raises ParseQualityError carrying the parse (so it
can be quarantined, not filed), and the CLI quarantines a
gated parse with exit code 3 instead of writing the output.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_convert", HERE.parents[1] / "wiki_convert.py")
wc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wc)

GOOD_MD = """# Quarterly Findings

The survey covered twelve neighbourhoods and found that
participation rose steadily across every quarter measured.

## Method

- Interviews with residents in each district
- A review of the published attendance records
- Comparison against the previous year's figures

The results suggest that weekend sessions drew the largest
crowds, while weekday evenings remained comparatively quiet
in most districts surveyed this year.
"""

GARBLED_MD = "� � ### $$$ %%% ^^^ &&& *** @@@ !!! ~~~ ��� ���"
REPETITIVE_MD = "the " * 80


class ParseQualityTests(unittest.TestCase):
    def test_good_parse_scores_good(self):
        q = wc.parse_quality(GOOD_MD)
        self.assertGreaterEqual(q["score"], 0.5)
        self.assertEqual(q["verdict"], "good")
        self.assertGreater(q["components"]["words"], 40)

    def test_empty_parse_scores_zero(self):
        self.assertEqual(wc.parse_quality("")["score"], 0.0)
        self.assertEqual(wc.parse_quality("  \n\n ")["score"], 0.0)
        self.assertEqual(wc.parse_quality("")["verdict"], "poor")

    def test_garbled_parse_scores_poor(self):
        q = wc.parse_quality(GARBLED_MD)
        self.assertLess(q["score"], 0.5)
        self.assertEqual(q["verdict"], "poor")

    def test_repetitive_parse_scores_poor(self):
        q = wc.parse_quality(REPETITIVE_MD)
        self.assertLess(q["score"], 0.5)
        self.assertLess(q["components"]["diversity"], 0.2)

    def test_report_records_parse_quality(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "note.md"
            src.write_text(GOOD_MD, encoding="utf-8")
            _md, report = wc.convert_with_report(src)
            self.assertIn("parse_quality", report)
            self.assertEqual(report["parse_quality"]["verdict"],
                             "good")

    def test_gate_raises_with_parse_attached(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "junk.txt"
            src.write_text(GARBLED_MD, encoding="utf-8")
            with self.assertRaises(wc.ParseQualityError) as cm:
                wc.convert_with_report(src, quality_threshold=0.5)
            self.assertIn("parse_quality", cm.exception.report)
            self.assertTrue(cm.exception.md)

    def test_gate_passes_good_parse(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "note.md"
            src.write_text(GOOD_MD, encoding="utf-8")
            md, report = wc.convert_with_report(
                src, quality_threshold=0.5)
            self.assertIn("Quarterly Findings", md)

    def test_cli_quarantines_gated_parse(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "junk.txt"
            src.write_text(GARBLED_MD, encoding="utf-8")
            out = Path(td) / "out.md"
            qdir = Path(td) / "quarantine"
            rc = wc.main([str(src), "-o", str(out),
                          "--quality-threshold", "0.5",
                          "--quarantine-dir", str(qdir)])
            self.assertEqual(rc, 3)
            self.assertFalse(out.exists())  # NOT filed
            qmd = qdir / "junk.quarantined.md"
            qjson = qdir / "junk.quarantined.ingest.json"
            self.assertTrue(qmd.is_file())
            report = json.loads(qjson.read_text(encoding="utf-8"))
            self.assertEqual(report["parse_quality"]["verdict"],
                             "poor")

    def test_cli_without_gate_files_as_before(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "note.md"
            src.write_text(GOOD_MD, encoding="utf-8")
            out = Path(td) / "out.md"
            rc = wc.main([str(src), "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
