"""Tests for scripts/wiki_jotter.py (Marathon R7 lane BB;
Jotter pattern, GPL — re-implemented only, no code copied).

Pins: (a) source_record parsing + validation (valid record
clean; missing title, missing locator, bad year, unknown field
all findings); (b) cited-by inverts sources lists, cite markers
and wikilinks, and answers a single-target query; (c)
unconnected separates no-neighbours from not-in-index; all
report-only.

Run: python3 -m unittest scripts.tests.test_wiki_jotter
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_jotter", SCRIPTS / "wiki_jotter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()

GOOD = """---
title: "Harbour Notes"
type: source
sources: [raw/sources/harbour.md]
source_record:
  title: "On Harbours"
  authors: [A. Marin]
  year: 2024
  url: "https://example.org/harbours"
  accessed: 2026-10-01
---

Body citing the raw file. ^[cite: raw/sources/harbour.md#L1-L2]
See also [[reader]].
"""
READER = """---
title: "Reader"
type: concept
sources: []
---

Reads [[harbour-notes]] closely.
"""
LONELY = """---
title: "Lonely"
type: concept
sources: []
---

No links at all.
"""
BAD = """---
title: "Bad Record"
type: source
sources: []
source_record:
  authors: [X. Y]
  year: 24
  isbn: "978"
---

Body.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_jotter.py", self.root / "scripts")
        wiki = self.root / "wiki"
        wiki.mkdir(parents=True)
        (wiki / "harbour-notes.md").write_text(GOOD, encoding="utf-8")
        (wiki / "reader.md").write_text(READER, encoding="utf-8")
        (wiki / "lonely.md").write_text(LONELY, encoding="utf-8")
        (wiki / "bad.md").write_text(BAD, encoding="utf-8")
        (wiki / "index.md").write_text(
            "# Index\n\n- [[harbour-notes]]\n- [[reader]]\n- [[bad]]\n",
            encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        self.tool = self.root / "scripts" / "wiki_jotter.py"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(self.tool), *argv],
                              capture_output=True, text=True)


class ValidateTests(Fixture):
    def test_good_record_clean_bad_record_flagged(self):
        report = MOD.validate(self.root)
        by_page = {p["page"]: p["problems"] for p in report["pages"]}
        self.assertEqual(by_page["wiki/harbour-notes.md"], [])
        bad = by_page["wiki/bad.md"]
        self.assertTrue(any("title" in p for p in bad))
        self.assertTrue(any("locator" in p for p in bad))
        self.assertTrue(any("year" in p for p in bad))
        self.assertTrue(any("unknown field" in p for p in bad))

    def test_validate_cli_exit(self):
        self.assertEqual(self.run_cli("validate").returncode, 1)


class CitedByTests(Fixture):
    def test_reverse_listing(self):
        report = MOD.cited_by(self.root, "raw/sources/harbour.md")
        self.assertIn("wiki/harbour-notes.md", report["cited_by"])

    def test_wikilink_citation(self):
        report = MOD.cited_by(self.root, "harbour-notes")
        self.assertIn("wiki/reader.md", report["cited_by"])

    def test_uncited_target_empty(self):
        report = MOD.cited_by(self.root, "lonely")
        self.assertEqual(report["cited_by"], [])


class UnconnectedTests(Fixture):
    def test_lonely_is_both_findings(self):
        report = MOD.unconnected(self.root)
        self.assertIn("wiki/lonely.md", report["no_neighbours"])
        self.assertIn("wiki/lonely.md", report["not_in_index"])
        self.assertNotIn("wiki/harbour-notes.md",
                         report["no_neighbours"])
        self.assertNotIn("wiki/reader.md", report["not_in_index"])

    def test_unconnected_cli_exit(self):
        self.assertEqual(self.run_cli("unconnected").returncode, 1)


if __name__ == "__main__":
    unittest.main()
