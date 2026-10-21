"""Tests for scripts/wiki_evidence_ttl.py (EU-N5) — pins:
a page inside its TTL is current; a page past as_of+TTL is
due with the right overdue count; TTL-without-as-of, a bad
date and a bad TTL are invalid; as_of without TTL is the
honest no-ttl state; pages with no evidence fields are
outside the convention; filings are excluded. Fixture trees
in temp dirs only; the judging date is injected, never the
wall clock.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_evidence_ttl", HERE.parents[1] / "wiki_evidence_ttl.py")
ttl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ttl)

TODAY = date(2026, 2, 1)


def write(root, rel, extra_fm=""):
    p = root / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\ntitle: T\ntype: concept\ncreated: 2026-01-01\n"
        "updated: 2026-01-01\nsources: []\ntags: [demo]\n"
        f"{extra_fm}---\n\n# T\n\nBody.\n", encoding="utf-8")


class EvidenceTtlTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "wiki").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_current_due_and_plain(self):
        write(self.root, "concepts/current.md",
              "evidence_as_of: 2026-01-20\nevidence_ttl_days: 30\n")
        write(self.root, "concepts/due.md",
              "evidence_as_of: 2026-01-01\nevidence_ttl_days: 10\n")
        write(self.root, "concepts/plain.md")
        r = ttl.check(self.root, TODAY)
        self.assertEqual(r["current_count"], 1)
        self.assertEqual(r["due_count"], 1)
        self.assertEqual(r["due"][0]["page"], "wiki/concepts/due.md")
        self.assertEqual(r["due"][0]["due"], "2026-01-11")
        self.assertEqual(r["due"][0]["days_overdue"], 21)
        self.assertEqual(r["with_evidence_fields"], 2)

    def test_ttl_forms(self):
        write(self.root, "concepts/a.md",
              "evidence_as_of: 2026-01-01\nevidence_ttl: 45d\n")
        r = ttl.check(self.root, TODAY)
        self.assertEqual(r["current"][0]["ttl_days"], 45)
        self.assertEqual(r["current"][0]["due"], "2026-02-15")

    def test_invalid_forms(self):
        write(self.root, "concepts/noasof.md", "evidence_ttl_days: 30\n")
        write(self.root, "concepts/baddate.md",
              "evidence_as_of: soon\nevidence_ttl_days: 30\n")
        write(self.root, "concepts/badttl.md",
              "evidence_as_of: 2026-01-01\nevidence_ttl_days: whenever\n")
        r = ttl.check(self.root, TODAY)
        self.assertEqual(r["invalid_count"], 3)
        self.assertEqual(r["due_count"], 0)

    def test_as_of_without_ttl_and_filings_excluded(self):
        write(self.root, "concepts/dated.md", "evidence_as_of: 2020-01-01\n")
        write(self.root, "filings/old.md",
              "evidence_as_of: 2020-01-01\nevidence_ttl_days: 1\n")
        r = ttl.check(self.root, TODAY)
        self.assertEqual(r["no_ttl_count"], 1)
        self.assertEqual(r["due_count"], 0)

    def test_exit_codes(self):
        write(self.root, "concepts/due.md",
              "evidence_as_of: 2026-01-01\nevidence_ttl_days: 10\n")
        rc = ttl.main(["x", "--root", str(self.root),
                       "--as-of", "2026-02-01"])
        self.assertEqual(rc, 1)
        rc = ttl.main(["x", "--root", str(self.root),
                       "--as-of", "not-a-date"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
