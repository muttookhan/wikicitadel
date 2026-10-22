#!/usr/bin/env python3
"""Tests for the statement-level label pack in
scripts/wiki_lint_lanes.py (build wave 5, 2026-10-22; idea
sources: jpaarhuis/open-dossier's four-way statement label,
VitaeContext, and Local Contexts' verification label states
— clean re-implementation of the grammar and checker).

The pack: bracketed kind labels ([SOURCE] / [INTERPRETATION]
/ [HYPOTHESIS] / [DECISION]) and verification labels
([verified] / [non-verified]) at a statement's start, a
closed vocabulary (unknown flags and unknown ALL-CAPS
labels are findings, named), open hypotheses listed,
contradictions on labelled statements recorded with both
source IDs, and the claims-to-avoid census over entity
pages. The counting rules mirror the editorial markers':
fenced code and inline code never count, frontmatter is
skipped, a mention in bare prose counts.

The module under test loads sibling lane modules at import
time; like the COGA and rating-table tests, this test loads
a COPY of it from a temp scripts dir whose siblings are
minimal stubs.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
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


def load_lanes():
    tmp = Path(tempfile.mkdtemp(prefix="lanes-labels-")) / "scripts"
    tmp.mkdir(parents=True)
    for name, body in STUBS.items():
        (tmp / f"{name}.py").write_text(body, encoding="utf-8")
    shutil.copy(SCRIPTS / "wiki_lint_lanes.py",
                tmp / "wiki_lint_lanes.py")
    spec = importlib.util.spec_from_file_location(
        "wiki_lint_lanes_labels_under_test",
        tmp / "wiki_lint_lanes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lanes = load_lanes()

LABELLED_PAGE = FM + """# Fixture

[SOURCE] The report states the sky is blue. ^[cite: raw/sources/a.md#L1-L2]

[INTERPRETATION] [verified] Read together, the sources suggest rain.

- [HYPOTHESIS] Usage will double by spring.
- [DECISION] [non-verified] We ship on Friday.

> [SOURCE] A quoted restatement inside a blockquote.

A mid-statement [SOURCE] mention does not count.

`[SOURCE]` in backticks is a mention, not a use, and
`{{frobnicate}}` in backticks is not a flag either.

```
[HYPOTHESIS] inside a fence does not count.
```

[Text](https://example.com) at line start is a link.

[[wikilink]] at line start is a link.

- [ ] an open checkbox.
- [DR] a short sigil, not a label.
- [hawk-checked] a lowercase token, not a label.

[SOURCE] The claim is contested. {{disputed}} ^[cite: raw/sources/a.md#L1-L2] and [[sources/b-page]]

{{frobnicate}} marks nothing known.

[TODO] Not a vocabulary label.
"""


class StatementLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="labels-wiki-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "wiki").mkdir()

    def write_page(self, name, text):
        path = self.tmp / "wiki" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_kind_and_verification_counts(self):
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        result = lanes.statement_labels(self.tmp)
        self.assertEqual(result["kind_counts"],
                         {"SOURCE": 3, "INTERPRETATION": 1,
                          "HYPOTHESIS": 1, "DECISION": 1})
        self.assertEqual(result["verification_counts"],
                         {"verified": 1, "non-verified": 1})
        self.assertEqual(result["labelled_total"], 6)

    def test_open_hypotheses_listed(self):
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        result = lanes.statement_labels(self.tmp)
        self.assertEqual(len(result["open_hypotheses"]), 1)
        self.assertEqual(result["open_hypotheses"][0]["page"],
                         "wiki/concepts/labelled.md")
        self.assertIn("Usage will double",
                      result["open_hypotheses"][0]["excerpt"])

    def test_disputed_labelled_records_both_source_ids(self):
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        result = lanes.statement_labels(self.tmp)
        self.assertEqual(len(result["disputed_labelled"]), 1)
        entry = result["disputed_labelled"][0]
        self.assertEqual(entry["kind"], "SOURCE")
        self.assertEqual(entry["source_ids"],
                         ["raw/sources/a.md", "sources/b-page"])

    def test_unknown_vocabulary_named(self):
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        result = lanes.statement_labels(self.tmp)
        self.assertEqual([h["name"] for h in result["unknown_flags"]],
                         ["frobnicate"])
        self.assertEqual([h["name"] for h in result["unknown_labels"]],
                         ["TODO"])

    def test_backtick_mentions_are_not_uses(self):
        # The fixture's backticked `[SOURCE]` and `{{frobnicate}}`
        # mentions must not inflate either census: kind SOURCE
        # stays 3 (paragraph, blockquote, disputed) and the only
        # frobnicate finding is the bare-prose one.
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        result = lanes.statement_labels(self.tmp)
        self.assertEqual(result["kind_counts"]["SOURCE"], 3)
        self.assertEqual(len(result["unknown_flags"]), 1)

    def test_known_flags_are_not_unknown(self):
        self.write_page("concepts/marks.md", FM + (
            "# Marks\n\nA claim. {{cite}}\n\nAnother. {{clarify}}\n"))
        result = lanes.statement_labels(self.tmp)
        self.assertEqual(result["unknown_flags"], [])
        markers = lanes.editorial_markers(self.tmp)
        self.assertEqual(markers["counts"],
                         {"cite": 1, "clarify": 1, "disputed": 0})

    def test_deterministic(self):
        self.write_page("concepts/labelled.md", LABELLED_PAGE)
        first = lanes.statement_labels(self.tmp)
        second = lanes.statement_labels(self.tmp)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


class ClaimsToAvoidTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cta-wiki-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "wiki" / "entities").mkdir(parents=True)

    def write_entity(self, name, text):
        (self.tmp / "wiki" / "entities" / name).write_text(
            text, encoding="utf-8")

    def test_section_collected_until_next_heading(self):
        self.write_entity("person-a.md", FM + (
            "# Person A\n\n## Claims to avoid\n\n"
            "- That A holds a doctorate — no source states it.\n"
            "- That A lives in Ohio — the record says Indiana.\n\n"
            "## Notes\n\n- Not an avoided claim.\n"))
        self.write_entity("person-b.md", FM + "# Person B\n\nText.\n")
        result = lanes.claims_to_avoid(self.tmp)
        self.assertEqual(result["pages_checked"], 2)
        self.assertEqual(result["with_section"], 1)
        self.assertEqual(result["sections"][0]["page"],
                         "wiki/entities/person-a.md")
        self.assertEqual(
            result["sections"][0]["claims"],
            ["That A holds a doctorate — no source states it.",
             "That A lives in Ohio — the record says Indiana."])

    def test_no_entities_dir_is_an_empty_census(self):
        result = lanes.claims_to_avoid(self.tmp / "nowhere")
        self.assertEqual(result["pages_checked"], 0)
        self.assertEqual(result["with_section"], 0)


def _empty_lane_dicts():
    empty_lane = {"count": 0, "top": None, "pages_scanned": 0,
                  "statements": 0, "cases_open": 0}
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
               "orphan_count": 0, "orphans": [], "validator_exit": 0}
    leaks_lane = {"new_total": 0, "baselined_total": 0,
                  "verdict": "clean", "baseline_present": True,
                  "surfaces": []}
    gate = {"live": [], "live_count": 0, "historical_count": 0,
            "forms": 0, "files_scanned": 0}
    annotations = {"count": 0, "items": [], "sources": 0}
    return empty_lane, stale, missing, leaks_lane, gate, annotations


class RenderTests(unittest.TestCase):

    def _quotes(self, with_labels):
        quotes = {"checked": 0, "pages": 0, "verified": 0,
                  "divergences": [],
                  "caveats": {"checked": 0, "carried": 0,
                              "findings": []},
                  "treatment": {
                      "events": 0, "subjects": 0,
                      "subjects_by_grade": {"followed": 0,
                                            "questioned": 0,
                                            "caution": 0,
                                            "negative": 0},
                      "treated_pages": [], "grounds_edges": 0,
                      "resting_pages": 0, "weakened": [],
                      "weakened_count": 0},
                  "markers": {"counts": {"cite": 0, "clarify": 0,
                                         "disputed": 0},
                              "total": 0, "locations": []}}
        if with_labels:
            quotes["labels"] = {
                "kind_counts": {"SOURCE": 1, "INTERPRETATION": 0,
                                "HYPOTHESIS": 1, "DECISION": 0},
                "verification_counts": {"verified": 0,
                                        "non-verified": 1},
                "labelled_total": 2,
                "locations": [
                    {"page": "wiki/concepts/x.md", "line": 9,
                     "kind": "HYPOTHESIS", "verification": None,
                     "excerpt": "[HYPOTHESIS] It doubles."}],
                "open_hypotheses": [
                    {"page": "wiki/concepts/x.md", "line": 9,
                     "excerpt": "[HYPOTHESIS] It doubles."}],
                "disputed_labelled": [],
                "unknown_flags": [
                    {"page": "wiki/concepts/x.md", "line": 12,
                     "name": "frobnicate", "excerpt": "x"}],
                "unknown_labels": [],
                "claims_to_avoid": {"pages_checked": 5,
                                    "with_section": 1,
                                    "sections": [
                                        {"page": "wiki/entities/a.md",
                                         "claims": ["That A is X."]}]}}
        return quotes

    def _render(self, quotes):
        empty_lane, stale, missing, leaks_lane, gate, annotations = \
            _empty_lane_dicts()
        return lanes.render(
            {"contradictions": empty_lane, "stale": stale,
             "missing": missing, "leaks": leaks_lane,
             "quotes": quotes, "decision_gate": gate,
             "annotations": annotations},
            "2026-10-22", "Lens note.")

    def test_render_includes_labels_subsection(self):
        report = self._render(self._quotes(with_labels=True))
        self.assertIn("### Statement labels (Lane 5, continued)",
                      report)
        self.assertIn("HYPOTHESIS 1", report)
        self.assertIn("Open hypotheses", report)
        self.assertIn("{{frobnicate}}", report)
        self.assertIn("Claims to avoid: **1** of 5", report)
        self.assertIn("That A is X.", report)

    def test_render_without_labels_key_still_works(self):
        report = self._render(self._quotes(with_labels=False))
        self.assertIn("### Statement labels (Lane 5, continued)",
                      report)
        self.assertIn("**0** labelled statement(s)", report)


if __name__ == "__main__":
    unittest.main()
