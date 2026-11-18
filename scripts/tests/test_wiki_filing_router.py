"""Tests for scripts/wiki_filing_router.py (Marathon R3 TB5 row 1,
crow-hq pattern): routing proposals carry a destination, a
confidence and reasons; agent filings route to the filings area;
an audit flags declared-vs-routed misfilings only at confidence
>= 0.6. Run: python3 -m unittest scripts.tests.test_wiki_filing_router
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_filing_router as wfr  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="router-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class RouteTests(Fixture):
    def test_agent_filing_routes_to_filings_area(self):
        p = self.write("f.md", "---\ntitle: X\ntype: filing\nby: grok\n"
                               "---\n\nA filing body.\n")
        prop = wfr.route_item(p)
        self.assertEqual(prop["destination"], "filings-area")
        self.assertGreaterEqual(prop["confidence"], 0.6)
        self.assertTrue(prop["reasons"])
        self.assertTrue(prop["proposal_only"])

    def test_idea_routes_to_ideas(self):
        p = self.write("i.md", "---\ntitle: Y\ntype: idea\n---\n\nMaybe.\n")
        self.assertEqual(wfr.route_item(p)["destination"], "ideas")

    def test_ruling_request_routes_to_review(self):
        p = self.write("r.md", "---\ntitle: Z\n---\n\nThis needs an "
                               "owner decision before anything moves.\n")
        self.assertEqual(wfr.route_item(p)["destination"], "review-queue")

    def test_audit_flags_misfiling(self):
        self.write("bad.md", "---\ntitle: B\ntype: filing\nby: hark\n"
                             "destination: ideas\n---\n\nBody.\n")
        self.write("ok.md", "---\ntitle: O\ntype: idea\n"
                            "destination: ideas\n---\n\nBody.\n")
        bad = wfr.audit(self.root)
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["declared"], "ideas")
        self.assertEqual(bad[0]["routed"], "filings-area")


if __name__ == "__main__":
    unittest.main()
