"""Tests for the CommonMark 0.31.2 conformance subset against
the Lens renderer (Marathon Round 6, lane BA, item 1).

The subset (evaluation/commonmark-conformance.json) is a
bounded, CC BY-SA 4.0-attributed selection of the spec's own
examples. This test:

- validates the pin (evaluation/markdown-dialect.json) and
  the subset's shape/attribution/provenance;
- runs every case through lenslib.render_markdown and
  asserts the cases NOT recorded as divergences pass under
  the documented normalisation;
- asserts the ACTUAL divergence set equals the RECORDED
  known_divergences set exactly — a new divergence fails,
  and so does a recorded divergence that no longer diverges
  (a silently fixed renderer is a record error until the
  subset file is updated on the record);
- never edits the renderer: divergences are findings.

Run:  python3 -m unittest discover -s tools/lens/tests -v
"""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location(
    "wiki_markdown_dialect", ROOT / "scripts" / "wiki_markdown_dialect.py")
wmd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wmd)
spec2 = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
lenslib = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(lenslib)


class PinTest(unittest.TestCase):
    def test_pin_and_subset_validate(self):
        pin = wmd.load_pin(ROOT / "evaluation" / "markdown-dialect.json")
        cases = wmd.load_cases(
            ROOT / "evaluation" / "commonmark-conformance.json")
        self.assertEqual(wmd.check_pin(pin, cases), [])
        self.assertEqual(pin["dialect"], "CommonMark")
        self.assertEqual(pin["spec_version"], "0.31.2")

    def test_subset_is_bounded_and_covers_corpus_constructs(self):
        cases = wmd.load_cases(
            ROOT / "evaluation" / "commonmark-conformance.json")
        rows = cases["cases"]
        self.assertGreaterEqual(len(rows), 20)
        self.assertLessEqual(len(rows), 40)
        sections = " ".join(r["section"] for r in rows)
        for construct in ("ATX headings", "Block quotes", "Lists",
                          "Code spans", "Emphasis", "Links",
                          "Fenced code"):
            self.assertIn(construct, sections)
        # No table case: CommonMark 0.31.2 defines no tables.
        self.assertNotIn("table", sections.lower())


class ConformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = wmd.load_cases(
            ROOT / "evaluation" / "commonmark-conformance.json")
        cls.report = wmd.run_conformance(cls.cases, lenslib=lenslib)

    def test_unrecorded_cases_all_pass(self):
        recorded = {e["id"] for e in self.cases["known_divergences"]}
        failed = [r["id"] for r in self.report["results"]
                  if r["status"] == "diverge"
                  and r["id"] not in recorded]
        self.assertEqual(failed, [])
        passed = set(self.report["passed"])
        self.assertTrue(passed)  # the renderer does conform in part

    def test_divergence_set_matches_record_exactly(self):
        new, healed = wmd.divergence_drift(self.cases, self.report)
        self.assertEqual(new, [],
                         "new renderer divergences not on the record")
        self.assertEqual(healed, [],
                         "recorded divergences that no longer "
                         "diverge — update the record, do not let "
                         "it go stale")

    def test_recorded_divergences_carry_observed_output(self):
        observed = {d["id"]: d["observed"]
                    for d in self.report["diverged"]}
        for entry in self.cases["known_divergences"]:
            self.assertEqual(entry["observed"],
                             observed[entry["id"]])
            self.assertTrue(entry.get("note"))


if __name__ == "__main__":
    unittest.main()
