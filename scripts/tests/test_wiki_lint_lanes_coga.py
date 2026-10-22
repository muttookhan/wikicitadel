#!/usr/bin/env python3
"""Tests for the COGA structure checklist in
scripts/wiki_lint_lanes.py (build wave 2, 2026-10-22; clean
re-implementation from the W3C COGA guidance "Making Content
Usable" — idea only).

The rule set: over the compiled layer, seven mechanically
decidable structure checks — summary lead on long pages,
unbroken heading hierarchy, section chunking, introduced
lists/tables, short paragraphs, descriptive link text, and
frontmatter furniture (title / type). Findings carry the
measured value against the named house budget; the check
reports structure, never wording.

The module under test loads sibling lane modules at import
time; like the rating-table tests, this test loads a COPY
of it from a temp scripts dir whose siblings are minimal
stubs — except wiki_observe, whose stub carries a small
faithful parse_frontmatter (the COGA checks read title /
type / status through it; the fixtures use only the shapes
the stub parses).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

OBSERVE_STUB = '''
def parse_frontmatter(text):
    """Small faithful frontmatter parse for fixtures:
    `key: value` lines and `key:` + `  - item` lists."""
    if not text.startswith("---\\n"):
        return {}, text
    end = text.find("\\n---\\n", 4)
    if end == -1:
        return {}, text
    fields = {}
    key = None
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and key is not None:
            prev = fields.get(key)
            if not isinstance(prev, list):
                prev = [prev] if prev else []
            prev.append(line[4:].strip())
            fields[key] = prev
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields, text[end + 5:]
'''

STUBS = {
    "wiki_observe": OBSERVE_STUB,
    "wiki_leak_lint": "",
    "wiki_decision_gate": "",
    "wiki_cite_lock": "",
    "wiki_annotate": "",
    "wiki_reverify": "",
    "wiki_treatment": "",
}

FM = ("---\ntitle: Fixture\ntype: concept\ncreated: 2026-10-22\n"
      "updated: 2026-10-22\nsources: []\ntags: [test]\n---\n\n")


def words(n, token="word"):
    return " ".join([token] * n)


def load_lanes():
    tmp = Path(tempfile.mkdtemp(prefix="lanes-coga-")) / "scripts"
    tmp.mkdir(parents=True)
    for name, body in STUBS.items():
        (tmp / f"{name}.py").write_text(body, encoding="utf-8")
    shutil.copy(SCRIPTS / "wiki_lint_lanes.py",
                tmp / "wiki_lint_lanes.py")
    spec = importlib.util.spec_from_file_location(
        "wiki_lint_lanes_coga_under_test",
        tmp / "wiki_lint_lanes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lanes = load_lanes()


class CogaFindingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="coga-wiki-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "wiki").mkdir()

    def write_page(self, name, text):
        path = self.tmp / "wiki" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def checks(self, result):
        return [f["check"] for f in result["findings"]]

    def test_clean_page_has_no_findings(self):
        self.write_page("clean.md", FM + (
            "# Clean\n\nA short opening summary of what this"
            " page holds and why.\n\n## Part one\n\nThis"
            " sentence introduces the list below.\n\n"
            "- one\n- two\n\n## Part two\n\nClosing prose"
            " with a [descriptive destination](https://"
            "example.com/page) named.\n"))
        result = lanes.coga_findings(self.tmp)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["pages_checked"], 1)
        self.assertEqual(set(result["by_check"]),
                         {c for c, _ in lanes.COGA_CHECKS})
        self.assertTrue(all(v == 0
                            for v in result["by_check"].values()))

    def test_long_page_without_summary_lead_fires(self):
        section = "\n\n## Section\n\n" + words(350) + "\n"
        self.write_page("long.md", FM + "# Long\n" + section * 2)
        result = lanes.coga_findings(self.tmp)
        self.assertIn("no-summary-lead", self.checks(result))
        finding = [f for f in result["findings"]
                   if f["check"] == "no-summary-lead"][0]
        self.assertIn("house budget", finding["evidence"])

    def test_long_page_with_summary_lead_is_clean(self):
        section = "\n\n## Section\n\n" + words(350) + "\n"
        self.write_page("long.md", FM + (
            "# Long\n\nThis page summarises the whole matter"
            " up front, in one short paragraph.\n"
            + section * 2))
        result = lanes.coga_findings(self.tmp)
        self.assertNotIn("no-summary-lead", self.checks(result))

    def test_short_page_needs_no_summary_lead(self):
        self.write_page("short.md", FM + "# Short\n\n"
                        "## Only section\n\n" + words(50) + "\n")
        result = lanes.coga_findings(self.tmp)
        self.assertNotIn("no-summary-lead", self.checks(result))

    def test_heading_level_skip_fires_with_line(self):
        self.write_page("skip.md", FM + (
            "# Top\n\nIntro prose.\n\n### Too deep\n\n"
            "Body text.\n"))
        result = lanes.coga_findings(self.tmp)
        skips = [f for f in result["findings"]
                 if f["check"] == "heading-level-skip"]
        self.assertEqual(len(skips), 1)
        self.assertIn("H1", skips[0]["evidence"])
        self.assertIn("H3", skips[0]["evidence"])
        self.assertGreater(skips[0]["line"], 1)

    def test_unbroken_section_fires_and_chunking_clears(self):
        self.write_page("wall.md", FM + (
            "# Wall\n\nLead.\n\n## One long run\n\n"
            + words(900) + "\n"))
        result = lanes.coga_findings(self.tmp)
        self.assertIn("unbroken-section", self.checks(result))
        self.write_page("wall.md", FM + (
            "# Wall\n\nLead.\n\n## One run\n\n" + words(450)
            + "\n\n### Second half\n\n" + words(450) + "\n"))
        result = lanes.coga_findings(self.tmp)
        self.assertNotIn("unbroken-section",
                         self.checks(result))

    def test_unintroduced_list_and_table_fire(self):
        self.write_page("bare.md", FM + (
            "# Bare\n\nLead prose.\n\n## Items\n\n"
            "- one\n- two\n\n## Grid\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n"))
        result = lanes.coga_findings(self.tmp)
        unintro = [f for f in result["findings"]
                   if f["check"] == "unintroduced-block"]
        self.assertEqual(len(unintro), 2)
        self.assertIn("list of 2 items",
                      unintro[0]["evidence"])
        self.assertIn("table of 3 rows",
                      unintro[1]["evidence"])

    def test_introduced_and_loose_lists_are_clean(self):
        self.write_page("intro.md", FM + (
            "# Intro\n\nLead prose.\n\n## Items\n\n"
            "The items below are the whole set.\n\n"
            "- one item with a wrapped\n  continuation line\n"
            "\n- two\n\n- three\n"))
        result = lanes.coga_findings(self.tmp)
        self.assertNotIn("unintroduced-block",
                         self.checks(result))

    def test_long_paragraph_boundary(self):
        self.write_page("para.md", FM + (
            "# Para\n\nLead.\n\n## Body\n\n" + words(150)
            + "\n\n" + words(151) + "\n"))
        result = lanes.coga_findings(self.tmp)
        longs = [f for f in result["findings"]
                 if f["check"] == "long-paragraph"]
        self.assertEqual(len(longs), 1)
        self.assertIn("151 words", longs[0]["evidence"])

    def test_non_descriptive_links_fire_descriptive_clean(self):
        self.write_page("links.md", FM + (
            "# Links\n\nLead prose.\n\nSee [click here]"
            "(https://example.com/a) and"
            " [https://example.com/b](https://example.com/b)"
            " but read [the COGA guidance]"
            "(https://example.com/c) and [[a-wiki-page]]"
            " freely.\n"))
        result = lanes.coga_findings(self.tmp)
        bad = [f for f in result["findings"]
               if f["check"] == "non-descriptive-link"]
        self.assertEqual(len(bad), 2)

    def test_fenced_code_is_not_structure(self):
        self.write_page("code.md", FM + (
            "# Code\n\nLead prose.\n\n```\n## Not a heading\n"
            "- not a list\n[click here](https://example.com)\n"
            "```\n\nDone.\n"))
        result = lanes.coga_findings(self.tmp)
        self.assertEqual(result["count"], 0)

    def test_missing_frontmatter_fields_fire(self):
        self.write_page("nofm.md", "# No frontmatter\n\n"
                        "Body prose only.\n")
        self.write_page("partial.md",
                        "---\ntitle: Only a title\n---\n\n"
                        "# Partial\n\nBody prose.\n")
        result = lanes.coga_findings(self.tmp)
        furn = [f for f in result["findings"]
                if f["check"] == "missing-frontmatter-field"]
        self.assertEqual(len(furn), 2)
        self.assertTrue(any("no parseable frontmatter" in
                            f["evidence"] for f in furn))
        self.assertTrue(any("`type`" in f["evidence"]
                            for f in furn))

    def test_tombstone_is_exempt(self):
        self.write_page("gone.md",
                        "---\nstatus: tombstoned\n---\n\n"
                        "This page was retired.\n")
        result = lanes.coga_findings(self.tmp)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["pages_checked"], 1)

    def test_excluded_dirs_and_files_are_not_checked(self):
        self.write_page("filings/note.md", "# Bare\n")
        self.write_page("talk/note.md", "# Bare\n")
        self.write_page("index.md", "# Bare\n")
        self.write_page("log.md", "# Bare\n")
        self.write_page("real.md", FM + "# Real\n\nProse.\n")
        result = lanes.coga_findings(self.tmp)
        self.assertEqual(result["pages_checked"], 1)
        self.assertEqual(result["count"], 0)

    def test_deterministic_across_runs(self):
        self.write_page("a.md", FM + (
            "# A\n\n## Items\n\n- one\n- two\n\n"
            + words(200) + "\n"))
        first = lanes.coga_findings(self.tmp)
        second = lanes.coga_findings(self.tmp)
        self.assertEqual(first, second)
        self.assertGreater(first["count"], 0)


class CogaRenderTests(unittest.TestCase):

    def _lanes_dict(self, coga):
        empty_lane = {"count": 0, "top": None,
                      "pages_scanned": 0, "statements": 0,
                      "cases_open": 0}
        stale = {"count": 0, "oldest": [], "scanned": 0,
                 "undated": 0, "cutoff": "2026-09-20",
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
                      "verdict": "clean",
                      "baseline_present": True, "surfaces": []}
        quotes = {"checked": 0, "pages": 0, "verified": 0,
                  "divergences": [],
                  "caveats": {"checked": 0, "carried": 0,
                              "findings": []},
                  "treatment": {
                      "events": 0, "subjects": 0,
                      "subjects_by_grade": {
                          "followed": 0, "questioned": 0,
                          "caution": 0, "negative": 0},
                      "treated_pages": [],
                      "grounds_edges": 0, "resting_pages": 0,
                      "weakened": [], "weakened_count": 0},
                  "markers": {
                      "counts": {"cite": 0, "clarify": 0,
                                 "disputed": 0},
                      "total": 0, "locations": []}}
        gate = {"live": [], "live_count": 0,
                "historical_count": 0, "forms": 0,
                "files_scanned": 0}
        annotations = {"count": 0, "items": [], "sources": 0}
        return {"contradictions": empty_lane, "stale": stale,
                "missing": missing, "leaks": leaks_lane,
                "quotes": quotes, "decision_gate": gate,
                "annotations": annotations, "coga": coga}

    def test_render_includes_coga_section(self):
        coga = {"count": 1,
                "findings": [{
                    "page": "wiki/concepts/x.md",
                    "check": "long-paragraph", "line": 9,
                    "evidence": "paragraph of 151 words"
                                " (house budget 150)"}],
                "by_check": {c: (1 if c == "long-paragraph"
                                 else 0)
                             for c, _ in lanes.COGA_CHECKS},
                "pages_checked": 3, "pages_with_findings": 1}
        report = lanes.render(self._lanes_dict(coga),
                              "2026-10-22", "Lens note.")
        self.assertIn("## COGA structure checklist", report)
        self.assertIn("`wiki/concepts/x.md` line 9", report)
        self.assertIn("**To clear this:**", report)

    def test_render_without_coga_key_still_works(self):
        data = self._lanes_dict(None)
        del data["coga"]
        report = lanes.render(data, "2026-10-22", "Lens note.")
        self.assertIn("## COGA structure checklist", report)
        self.assertIn("No findings this run.", report)


if __name__ == "__main__":
    unittest.main()
