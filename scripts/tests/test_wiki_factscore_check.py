#!/usr/bin/env python3
"""Pins wiki_factscore_check (Marathon R5 lane BB; Min et al.
FActScore pattern): per-claim verdicts at each claim's own
citation — supported / unsupported / missing-citation /
citation-unresolvable / citation-out-of-range — and the
no-auto-verify boundary: a check never modifies the page, and
a report path colliding with a checked page is refused.

Run:  python3 -m unittest discover -s scripts/tests
"""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wiki_factscore_check", SCRIPTS / "wiki_factscore_check.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SOURCE = """# Harbour notes

The harbour light flashes twice every ten seconds.
The keeper records each lamp change in the log book.
Boats approach the harbour only in daylight hours.
"""

PAGE = """---
title: Harbour Lights
type: source
created: 2026-01-15
updated: 2026-01-15
sources: [raw/sources/harbour.md]
tags: [fixture]
---

## Operation

The harbour light flashes twice every ten seconds at night.^[cite: raw/sources/harbour.md#L3-L3]
The harbour light was built by Martian engineers from Venus.^[cite: raw/sources/harbour.md#L3-L3]
The keeper paints the tower bright green every spring season.
A claim pointing at a vanished file entirely today.^[cite: raw/sources/gone.md#L1-L2]
A claim pointing beyond the end of the harbour notes.^[cite: raw/sources/harbour.md#L90-L99]
"""


class TestFactScoreCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "raw" / "sources").mkdir(parents=True)
        (self.root / "wiki" / "sources").mkdir(parents=True)
        (self.root / "raw" / "sources" / "harbour.md").write_text(SOURCE)
        self.page = self.root / "wiki" / "sources" / "harbour.md"
        self.page.write_text(PAGE)
        self.h = hashlib.sha256(self.page.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_claim_verdicts(self):
        rec = m.check_page(self.root, "wiki/sources/harbour.md")
        verdicts = [v["verdict"] for v in rec["verdicts"]]
        self.assertEqual(verdicts, [
            "supported",               # verbatim-supported claim
            "unsupported",             # citation present, no support
            "missing-citation",        # no marker at all
            "citation-unresolvable",   # cited file gone
            "citation-out-of-range",   # cited lines beyond EOF
        ])
        self.assertEqual(rec["counts"]["supported"], 1)
        self.assertEqual(rec["claims"], 5)
        # headings group the claims
        self.assertTrue(all(v["heading"] == "Operation"
                            for v in rec["verdicts"]))

    def test_never_auto_verifies_and_page_untouched(self):
        report = m.run(self.root, ["wiki/sources/harbour.md"], 0.35)
        self.assertFalse(report["auto_verified"])
        self.assertFalse(report["page_status_changed"])
        rec = report["records"][0]
        self.assertFalse(rec["auto_verified"])
        # the checked page is byte-identical after the run
        self.assertEqual(
            hashlib.sha256(self.page.read_bytes()).hexdigest(),
            self.h)
        text = self.page.read_text()
        self.assertNotIn("verified_until", text)
        self.assertNotIn("verified_by", text)

    def test_report_refuses_page_path_and_exit_codes(self):
        rc = m.main(["--root", str(self.root), "--out",
                     "wiki/sources/harbour.md", "check",
                     "wiki/sources/harbour.md"])
        self.assertEqual(rc, 4)
        self.assertEqual(
            hashlib.sha256(self.page.read_bytes()).hexdigest(),
            self.h)
        # mixed verdicts -> exit 1 (a finding)
        rc = m.main(["--root", str(self.root), "check",
                     "wiki/sources/harbour.md"])
        self.assertEqual(rc, 1)

    def test_all_supported_exits_zero(self):
        page = PAGE.split("The harbour light was built")[0] + "\n"
        # keep only the supported claim: rebuild a minimal page
        page = ("---\ntitle: H\ntype: source\ncreated: 2026-01-15\n"
                "updated: 2026-01-15\nsources: [raw/sources/harbour.md]\n"
                "tags: [fixture]\n---\n\n"
                "The harbour light flashes twice every ten "
                "seconds at night.^[cite: raw/sources/harbour.md#L3-L3]\n")
        self.page.write_text(page)
        rc = m.main(["--root", str(self.root), "check",
                     "wiki/sources/harbour.md"])
        self.assertEqual(rc, 0)

    def test_frontmatter_claim_is_an_atomic_claim(self):
        page = PAGE.replace(
            "tags: [fixture]\n---",
            'tags: [fixture]\nclaim: "The harbour light flashes '
            'twice every ten seconds at night."\n---')
        self.page.write_text(page)
        rec = m.check_page(self.root, "wiki/sources/harbour.md")
        self.assertEqual(rec["verdicts"][0]["kind"],
                         "frontmatter-claim")
        self.assertEqual(rec["verdicts"][0]["verdict"],
                         "missing-citation")


if __name__ == "__main__":
    unittest.main()
