"""Tests for scripts/wiki_maildir.py (item 55): the Maildir
correspondence check — headers, name form, id uniqueness,
index entries, the class B/C populations, duplicates."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_maildir as md  # noqa: E402

ID1 = "msg_" + "a1" * 16
ID2 = "msg_" + "b2" * 16


def filing(sender="Galen bot (galen@example.com)",
           ts="2030-10-17T00:37:14.281Z", local="2030-10-16",
           mid=ID1, subject="Hello"):
    return ("# Filing from %s — received %s (%s 20:37 EDT) — "
            "message id %s\nSubject: %s\n\nBody.\n"
            % (sender, ts, local, mid, subject))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="maildir-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "raw/filings/galen").mkdir(parents=True)
        (self.root / "raw/sources").mkdir(parents=True)
        (self.root / "wiki/filings").mkdir(parents=True)

    def good(self, ledger=True):
        write(self.root / "raw/filings/galen"
              / ("2030-10-16-%s.md" % ID1[4:12]), filing())
        if ledger:
            write(self.root / "wiki/filings/galen-filings.md",
                  "# ledger\nmessage %s\n" % ID1)


class Check(Fixture):
    def test_conforming_archive_has_no_gaps(self):
        self.good()
        rep = md.check(self.root)
        self.assertEqual(rep["gaps"], [])
        self.assertEqual(len(rep["a"]), 1)
        self.assertEqual(rep["a"][0]["indexed"], "ledger")

    def test_duplicate_message_id_surfaces(self):
        self.good()
        (self.root / "raw/filings/hugo").mkdir(parents=True)
        write(self.root / "raw/filings/hugo"
              / ("2030-10-16-%s.md" % ID1[4:12]), filing())
        write(self.root / "wiki/filings/hugo-filings.md",
              "message %s\n" % ID1)
        rep = md.check(self.root)
        self.assertTrue(any("duplicate" in g
                            for g in rep["gaps"]))

    def test_filename_suffix_mismatch(self):
        write(self.root / "raw/filings/galen/2030-10-16-zzzz9999.md"
              .replace("zzzz9999", "00000000"), filing())
        write(self.root / "wiki/filings/galen-filings.md",
              "message %s\n" % ID1)
        rep = md.check(self.root)
        self.assertTrue(any("filename suffix" in g
                            for g in rep["gaps"]))

    def test_filename_date_mismatch(self):
        write(self.root / "raw/filings/galen"
              / ("2030-10-10-%s.md" % ID1[4:12]), filing())
        write(self.root / "wiki/filings/galen-filings.md",
              "message %s\n" % ID1)
        rep = md.check(self.root)
        self.assertTrue(any("filename date" in g
                            for g in rep["gaps"]))

    def test_missing_subject_line(self):
        text = filing().replace("Subject: Hello\n", "")
        write(self.root / "raw/filings/galen"
              / ("2030-10-16-%s.md" % ID1[4:12]), text)
        write(self.root / "wiki/filings/galen-filings.md",
              "message %s\n" % ID1)
        rep = md.check(self.root)
        self.assertTrue(any("Subject" in g for g in rep["gaps"]))

    def test_unindexed_message_is_a_gap(self):
        self.good(ledger=False)
        write(self.root / "wiki/filings/galen-filings.md",
              "# empty ledger\n")
        rep = md.check(self.root)
        self.assertTrue(any("no index entry" in g
                            for g in rep["gaps"]))

    def test_class_b_indexed_and_unindexed(self):
        self.good()
        write(self.root / "raw/filings/galen/2030-10-16-notes.md",
              "# notes\n")
        write(self.root / "raw/filings/galen/2030-10-16-lost.md",
              "# lost\n")
        write(self.root / "wiki/filings/notes-page.md",
              "see 2030-10-16-notes.md\n")
        rep = md.check(self.root)
        b = {i["path"].split("/")[-1]: i for i in rep["b"]}
        self.assertTrue(b["2030-10-16-notes.md"]["indexed"])
        self.assertFalse(b["2030-10-16-lost.md"]["indexed"])
        self.assertTrue(any("lost" in g for g in rep["gaps"]))

    def test_class_c_counts_both_delimiter_styles(self):
        write(self.root / "raw/sources"
              / "2030-01-13-agent-mail-agent-inbox-full.md",
              "==== THREAD 1 (of 2) ====\nMessage 1 — Date: x\n"
              "==== THREAD 2 (of 2) ====\nMessage 1 — Date: y\n"
              "— Message 2 —\n")
        rep = md.check(self.root)
        self.assertEqual(rep["c"][0]["threads"], 2)
        self.assertEqual(rep["c"][0]["messages"], 3)

    def test_readme_and_gitkeep_are_not_records(self):
        self.good()
        write(self.root / "raw/filings/galen/README.md", "# r\n")
        write(self.root / "raw/filings/galen/.gitkeep", "")
        rep = md.check(self.root)
        self.assertEqual(len(rep["b"]), 0)

    def test_exit_codes(self):
        self.good()
        self.assertEqual(md.main(["check", "--root",
                                  str(self.root)]), 0)
        write(self.root / "raw/filings/galen/2030-10-16-lost.md",
              "# lost\n")
        self.assertEqual(md.main(["check", "--root",
                                  str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()
