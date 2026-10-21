"""Tests for scripts/wiki_triage.py (Marathon R3 TB5 row 3, Omnia
pattern): verdicts act/park/escalate follow the stated signal order;
closed items are skipped; a prior frontmatter verdict is respected,
never re-litigated; the pass edits nothing. Run:
python3 -m unittest scripts.tests.test_wiki_triage
"""
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_triage as wt  # noqa: E402

TODAY = date(2026, 10, 21)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="triage-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text):
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return p


class VerdictTests(Fixture):
    def test_ruling_request_escalates(self):
        p = self.write("a.md", "---\ntitle: A\nupdated: 2026-10-20\n---\n\n"
                               "Waiting: owner decision on the gate.\n")
        v = wt.verdict_for(p, TODAY)
        self.assertEqual(v["verdict"], "escalate")

    def test_next_step_acts(self):
        p = self.write("b.md", "---\ntitle: B\nupdated: 2026-10-20\n---\n\n"
                               "next: file the compiled page\n")
        self.assertEqual(wt.verdict_for(p, TODAY)["verdict"], "act")

    def test_plain_open_item_parks(self):
        p = self.write("c.md", "---\ntitle: C\nupdated: 2026-10-20\n---\n\n"
                               "Some notes with nothing pending.\n")
        self.assertEqual(wt.verdict_for(p, TODAY)["verdict"], "park")

    def test_stale_item_escalates(self):
        p = self.write("d.md", "---\ntitle: D\nupdated: 2026-09-01\n---\n\n"
                               "Old open item.\n")
        v = wt.verdict_for(p, TODAY, stale_days=14)
        self.assertEqual(v["verdict"], "escalate")
        self.assertIn("stale", v["reason"])

    def test_closed_item_skipped(self):
        p = self.write("e.md", "---\ntitle: E\nstatus: decided\n---\n\nx\n")
        self.assertIsNone(wt.verdict_for(p, TODAY))

    def test_prior_verdict_respected(self):
        p = self.write("f.md", "---\ntitle: F\nverdict: park\n"
                               "updated: 2026-09-01\n---\n\nOld but ruled.\n")
        v = wt.verdict_for(p, TODAY)
        self.assertEqual(v["verdict"], "park")
        self.assertTrue(v["already_triaged"])


if __name__ == "__main__":
    unittest.main()
