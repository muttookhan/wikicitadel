"""Tests for scripts/wiki_convo_query.py (Marathon R3 TB5 row 5,
DiaryKG pattern): queries over a fixture conversation log return
verbatim excerpts with correct file + line ranges; date, speaker,
keyword and decision-marker filters compose. Run:
python3 -m unittest scripts.tests.test_wiki_convo_query
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_convo_query as wcq  # noqa: E402

LOG = """# Conversation Log — fixture

### [2026-01-15 09:00 EST] Owner
I have completed the app setup.

### [2026-01-15 09:05 EST] Agent
Noted.

### [2026-01-16 09:00 EST] Owner
DECIDED: the demo corpus lives in the citadel.

### [2026-01-16 09:05 EST] Agent
Recorded. The citadel decision is filed.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="convo-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.log = self.root / "CONVERSATION-LOG.md"
        self.log.write_text(LOG, encoding="utf-8")


class QueryTests(Fixture):
    def test_all_entries_parsed_with_ranges(self):
        hits = wcq.query(self.log)
        self.assertEqual(len(hits), 4)
        self.assertEqual(hits[0]["lines"][0], 3)
        self.assertEqual(hits[0]["speaker"], "Owner")

    def test_speaker_and_date_filters(self):
        hits = wcq.query(self.log, date_="2026-01-16", speaker="owner")
        self.assertEqual(len(hits), 1)
        self.assertIn("DECIDED", hits[0]["excerpt"])

    def test_decisions_filter(self):
        hits = wcq.query(self.log, decisions=True)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["date"], "2026-01-16")

    def test_keyword_and_range(self):
        hits = wcq.query(self.log, keyword="citadel",
                         from_="2026-01-16", to="2026-01-16")
        self.assertEqual(len(hits), 2)
        for h in hits:
            start, end = h["lines"]
            lines = LOG.splitlines()
            self.assertIn("###", lines[start - 1])
            self.assertLessEqual(end, len(lines))


if __name__ == "__main__":
    unittest.main()
