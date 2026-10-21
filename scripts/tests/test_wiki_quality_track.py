#!/usr/bin/env python3
"""Pins wiki_quality_track (Marathon R6 lane BB; Brack et al.
ORKG pattern): expectations differ by track — a curated page
is held to citation expectations, an automatic page to
completeness expectations; a declared track wins; an absent
track is derived by the stated D1..D4 rules with the rule
named; an out-of-vocabulary track is a finding with derived
fallback; and the check never modifies a page.

Run:  python3 -m unittest discover -s scripts/tests
"""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wiki_quality_track", SCRIPTS / "wiki_quality_track.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

BASE = ["title: Fixture Page", "type: concept",
        "created: 2026-01-15", "updated: 2026-01-15",
        "sources: [raw/sources/x.md]", "tags: [fixture]",
        "stage: budding", "work_type: record"]
CITE = "A cited claim.^[cite: raw/sources/x.md#L1-L2]\n"


def page(extra=(), body="Body text.\n", drop=()):
    fm = [l for l in BASE
          if not any(l.startswith(d + ":") for d in drop)]
    fm += list(extra)
    return "---\n" + "\n".join(fm) + "\n---\n\n" + body


class TestQualityTrack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        self.pg = self.root / "wiki" / "concepts" / "p.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _rec(self):
        return m.check(self.root)["pages"][0]

    def test_declared_curated_complete_passes(self):
        self.pg.write_text(page(["quality_track: curated"],
                                body=CITE))
        rec = self._rec()
        self.assertEqual(rec["effective"], "curated")
        self.assertEqual(rec["source"], "declared")
        self.assertEqual(rec["findings"], [])
        self.assertEqual(m.main(["--root", str(self.root)]), 0)

    def test_curated_held_to_citation_expectations(self):
        self.pg.write_text(page(["quality_track: curated"],
                                body="No citations here.\n"))
        rec = self._rec()
        self.assertIn("curated-no-claim-citation",
                      rec["findings"])
        # the same page as automatic would owe completeness,
        # not citations — the tracks' expectations differ
        self.pg.write_text(page(["quality_track: automatic"],
                                body="No citations here.\n"))
        self.assertEqual(self._rec()["findings"], [])

    def test_curated_synthesis_owes_methods(self):
        self.pg.write_text(page(
            ["quality_track: curated", "work_type: synthesis"],
            body=CITE, drop=("work_type",)))
        self.assertIn("curated-missing-methods",
                      self._rec()["findings"])

    def test_automatic_held_to_completeness(self):
        self.pg.write_text(page(
            ["quality_track: automatic"],
            drop=("stage", "work_type", "tags")))
        findings = self._rec()["findings"]
        self.assertIn("automatic-missing-stage", findings)
        self.assertIn("automatic-missing-work-type", findings)
        self.assertIn("automatic-missing-tags", findings)

    def test_derivation_d1_owner_attested_is_curated(self):
        self.pg.write_text(page(["verified_until: 2027-01-01",
                                 "verified_by: owner"],
                                body=CITE))
        rec = self._rec()
        self.assertEqual(rec["effective"], "curated")
        self.assertEqual(rec["derivation"], "D1-owner-attested")
        self.assertEqual(rec["source"], "derived")

    def test_derivation_d2_claim_lifecycle_is_curated(self):
        self.pg.write_text(page(['claim: "A checkable claim."'],
                                body=CITE))
        rec = self._rec()
        self.assertEqual(rec["effective"], "curated")
        self.assertEqual(rec["derivation"], "D2-claim-lifecycle")

    def test_derivation_d3_evergreen_with_citation(self):
        self.pg.write_text(page(["stage: evergreen"], body=CITE,
                                drop=("stage",)))
        rec = self._rec()
        self.assertEqual(rec["effective"], "curated")
        self.assertEqual(rec["derivation"],
                         "D3-evergreen-with-citations")

    def test_derivation_d4_default_is_automatic(self):
        self.pg.write_text(page())
        rec = self._rec()
        self.assertEqual(rec["effective"], "automatic")
        self.assertEqual(rec["derivation"], "D4-default")
        self.assertEqual(rec["findings"], [])

    def test_invalid_track_falls_back_to_derivation(self):
        self.pg.write_text(page(["quality_track: gold-plated"]))
        rec = self._rec()
        self.assertIn("invalid-track", rec["findings"])
        self.assertEqual(rec["effective"], "automatic")
        self.assertEqual(rec["source"], "derived-fallback")
        self.assertEqual(m.main(["--root", str(self.root)]), 1)

    def test_check_never_modifies_pages(self):
        self.pg.write_text(page(["quality_track: curated"]))
        h = hashlib.sha256(self.pg.read_bytes()).hexdigest()
        m.check(self.root)
        self.assertEqual(
            hashlib.sha256(self.pg.read_bytes()).hexdigest(), h)


if __name__ == "__main__":
    unittest.main()
