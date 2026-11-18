#!/usr/bin/env python3
"""Tests for scripts/wiki_lint_lanes.py — the caveat-carriage
check in Lane 5 (wave-3 build, 2030-10-20).

The check is the compilation-fidelity companion to Lane 5's
quote verification: quotes verify that WORDING survived
compilation; caveat carriage verifies that QUALIFICATIONS
did. Detection is deliberately conservative (the Effortless
Academic failure it guards against is real, but a noisy lane
would be ignored): a source must state conditions explicitly
— a heading or bold-labelled line naming them, or repeated
conditional phrasing — and a page is flagged only when it
carries no caveat carriage at all.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_lanes_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_lint_lanes_under_test", SCRIPTS / "wiki_lint_lanes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lanes = load_lanes_module()


class SourceSignalTests(unittest.TestCase):

    def test_bold_limitation_label_is_strong(self):
        sig = lanes.source_caveat_signals(
            "Body text.\n\n**Limitation:** totals are partial.\n")
        self.assertGreaterEqual(sig["strong"], 1)
        self.assertTrue(lanes.source_states_caveats(sig))

    def test_bold_scope_label_is_strong(self):
        sig = lanes.source_caveat_signals(
            "**Scope:** the wiki repo and its history.\n")
        self.assertGreaterEqual(sig["strong"], 1)

    def test_limitations_heading_is_strong(self):
        sig = lanes.source_caveat_signals(
            "## Limitations\n\nOnly valid for past data.\n")
        self.assertGreaterEqual(sig["strong"], 1)

    def test_scope_heading_at_start_is_strong(self):
        sig = lanes.source_caveat_signals(
            "## Scope and method\n\nText.\n")
        self.assertGreaterEqual(sig["strong"], 1)

    def test_scope_word_mid_heading_is_not_strong(self):
        # "the build — Freeze the scope" is a process step title,
        # not a stated limitation on claims.
        sig = lanes.source_caveat_signals(
            "### the build — Freeze the scope\n\nText.\n")
        self.assertEqual(sig["strong"], 0)

    def test_plain_label_in_quoted_material_is_not_strong(self):
        # An email dump's "SCOPE:" line (a task instruction
        # inside quoted mail) is not the source stating its
        # own conditions.
        sig = lanes.source_caveat_signals(
            "From the inbox:\n\nSCOPE: Complete all pending"
            " work autonomously.\n")
        self.assertEqual(sig["strong"], 0)

    def test_repeated_conditional_phrasing_is_weak_signal(self):
        text = ("It holds only if the data is complete. "
                "It does not apply to drafts. "
                "The claim is valid only for 2030. "
                "Otherwise it does not apply.")
        sig = lanes.source_caveat_signals(text)
        self.assertGreaterEqual(sig["weak"], lanes.CAVEAT_WEAK_MIN)
        self.assertTrue(lanes.source_states_caveats(sig))

    def test_single_conditional_phrase_is_not_a_signal(self):
        sig = lanes.source_caveat_signals(
            "Use this only if you must.\n")
        self.assertFalse(lanes.source_states_caveats(sig))

    def test_plain_prose_has_no_signal(self):
        sig = lanes.source_caveat_signals(
            "# A plain note\n\nNothing conditional here.\n")
        self.assertEqual(sig["strong"], 0)
        self.assertEqual(sig["weak"], 0)
        self.assertFalse(lanes.source_states_caveats(sig))


class PageCarriageTests(unittest.TestCase):

    def test_conditions_and_limits_section_carries(self):
        self.assertTrue(lanes.page_carries_caveat(
            "# Page\n\n## Conditions and limits\n\nOnly 2030.\n"))

    def test_limitations_section_carries(self):
        self.assertTrue(lanes.page_carries_caveat(
            "# Page\n\n## Limitations\n\nPartial data.\n"))

    def test_caveat_callout_carries(self):
        self.assertTrue(lanes.page_carries_caveat(
            "# Page\n\n> [!note] Caveat\n> Only past data.\n"))

    def test_bold_label_line_carries(self):
        self.assertTrue(lanes.page_carries_caveat(
            "# Page\n\n**Limitation:** totals are partial.\n"))

    def test_literal_phrase_carries(self):
        self.assertTrue(lanes.page_carries_caveat(
            "# Page\n\nThe conditions and limits are stated"
            " in the summary above.\n"))

    def test_plain_page_does_not_carry(self):
        self.assertFalse(lanes.page_carries_caveat(
            "# Page\n\n## Summary\n\nEverything is fine.\n"))


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(sources, body):
    src_lines = "\n".join(f"  - {s}" for s in sources)
    return (f"---\ntitle: Fixture\ntype: source\n"
            f"created: 2030-10-20\nupdated: 2030-10-20\n"
            f"sources:\n{src_lines}\ntags: [fixture]\n---\n\n"
            f"# Fixture\n\n{body}\n")


class CaveatFindingsFixtureTests(unittest.TestCase):
    """caveat_findings over a small fixture tree."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        _write(root / "raw/sources/caveated.md",
               "# Source\n\n**Limitation:** the totals are"
               " partial; the delta is exact.\n")
        _write(root / "raw/sources/plain.md",
               "# Source\n\nA plain source with no stated"
               " conditions.\n")
        _write(root / "wiki/sources/page-a.md", _page(
            ["raw/sources/caveated.md"],
            "## Summary\n\nThe totals are 42."))
        _write(root / "wiki/sources/page-b.md", _page(
            ["raw/sources/caveated.md"],
            "## Summary\n\nThe totals are 42.\n\n"
            "## Conditions and limits\n\n"
            "The totals are partial."))
        _write(root / "wiki/sources/page-c.md", _page(
            ["raw/sources/plain.md"],
            "## Summary\n\nNothing conditional."))
        _write(root / "wiki/filings/page-d.md", _page(
            ["raw/sources/caveated.md"],
            "## Summary\n\nFilings are excluded."))
        cls.result = lanes.caveat_findings(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_checked_counts_pages_with_caveated_sources(self):
        # page-a (no carriage) + page-b (carriage); page-c's
        # source states nothing; page-d is in an excluded dir.
        self.assertEqual(self.result["checked"], 2)

    def test_carried_counts_pages_with_carriage(self):
        self.assertEqual(self.result["carried"], 1)

    def test_finding_names_page_and_source(self):
        self.assertEqual(len(self.result["findings"]), 1)
        finding = self.result["findings"][0]
        self.assertEqual(finding["page"], "wiki/sources/page-a.md")
        self.assertEqual(len(finding["sources"]), 1)
        self.assertEqual(finding["sources"][0]["source"],
                         "raw/sources/caveated.md")
        self.assertGreaterEqual(finding["sources"][0]["strong"], 1)


class RenderTests(unittest.TestCase):

    def test_render_includes_caveat_subsection(self):
        empty_lane = {"count": 0, "top": None, "pages_scanned": 0,
                      "statements": 0, "cases_open": 0}
        stale = {"count": 0, "oldest": [], "scanned": 0,
                 "undated": 0, "cutoff": "2030-09-20",
                 "semantic": [], "semantic_count": 0,
                 "claim_pages": 0, "outcomes_recorded": 0,
                 "talk_pages": 0, "attested_current": 0,
                 "attestation_expired": [],
                 "attestation_expired_count": 0,
                 "attestation_invalid": [], "reverify_due": [],
                 "reverify_due_count": 0}
        missing = {"broken_count": 0, "broken": [],
                   "orphan_count": 0, "orphans": [],
                   "validator_exit": 0}
        leaks_lane = {"new_total": 0, "baselined_total": 0,
                      "verdict": "clean", "baseline_present": True,
                      "surfaces": []}
        quotes = {"checked": 0, "pages": 0, "verified": 0,
                  "divergences": [],
                  "caveats": {"checked": 2, "carried": 1,
                              "findings": [
                                  {"page": "wiki/sources/x.md",
                                   "sources": [{
                                       "source": "raw/sources/y.md",
                                       "strong": 1, "weak": 0}]}]},
                  "treatment": {
                      "events": 1, "subjects": 1,
                      "subjects_by_grade": {
                          "followed": 0, "questioned": 0,
                          "caution": 0, "negative": 1},
                      "treated_pages": [
                          {"page": "wiki/sources/x.md",
                           "grade": "negative",
                           "claims": {"one claim": "negative"}}],
                      "grounds_edges": 3, "resting_pages": 2,
                      "weakened": [],
                      "weakened_count": 0},
                  "markers": {
                      "counts": {"cite": 1, "clarify": 0,
                                 "disputed": 0},
                      "total": 1,
                      "locations": [
                          {"page": "wiki/sources/x.md", "line": 9,
                           "kind": "cite",
                           "excerpt": "A claim. {{cite}}"}]}}
        gate = {"live": [], "live_count": 0,
                "historical_count": 0, "forms": 0,
                "files_scanned": 0}
        annotations = {"count": 0, "items": [], "sources": 0}
        report = lanes.render(
            {"contradictions": empty_lane, "stale": stale,
             "missing": missing, "leaks": leaks_lane,
             "quotes": quotes, "decision_gate": gate,
             "annotations": annotations},
            "2030-10-20", "Lens note.")
        self.assertIn("### Caveat carriage (Lane 5, continued)",
                      report)
        self.assertIn("caveats 1 lost-caveat candidate(s)", report)
        self.assertIn("`wiki/sources/x.md`", report)
        self.assertIn("`raw/sources/y.md`", report)
        # The item-10/15 subsections render from the same lane.
        self.assertIn("### Treatment signals (Lane 5, continued)",
                      report)
        self.assertIn("Transitive weakening: 0 page(s) weakened",
                      report)
        self.assertIn(
            "### Editorial markers (Lane 5, continued)", report)
        self.assertIn("{{cite}}", report)


if __name__ == "__main__":
    unittest.main()
