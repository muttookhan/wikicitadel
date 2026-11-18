#!/usr/bin/env python3
"""Tests for the rating-table legend rule in
scripts/wiki_lint_lanes.py (B3 governance round; pattern:
weijing143/llm-wiki-notes, via the feature survey).

The rule: a pipe table whose cells carry rating marks
(★☆✓✗✔✘●○◐⬤) with NO legend line in its surrounding section
is a finding carrying its line number.

The module under test loads sibling lane modules at import
time; this test therefore loads a COPY of it from a temp
scripts dir whose siblings are minimal stubs (the rating rule
is a pure function of the wiki tree and touches none of
them), so the test runs identically in a full tree and in a
minimal lane scratch.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

STUBS = {
    "wiki_observe": "def parse_frontmatter(text):\n"
                    "    return {}, text\n",
    "wiki_leak_lint": "",
    "wiki_decision_gate": "",
    "wiki_cite_lock": "",
    "wiki_annotate": "",
    "wiki_reverify": "",
    "wiki_treatment": "",
}

NO_LEGEND_PAGE = """# Ratings

## Scores

| Item | Rating |
|---|---|
| Alpha | ★★★ |
| Beta | ✓ |

Prose after the table.
"""

WITH_LEGEND_PAGE = """# Ratings

## Scores

Legend: ★ = strong, ✓ = present.

| Item | Rating |
|---|---|
| Alpha | ★★★ |
"""

LEGEND_ELSEWHERE_PAGE = """# Ratings

## Key

Legend: ★ = strong.

## Scores

| Item | Rating |
|---|---|
| Alpha | ★★★ |
"""

PLAIN_TABLE_PAGE = """# Data

| Item | Value |
|---|---|
| Alpha | 3 |
"""

PROSE_MARKS_PAGE = """# Notes

This approach is ✓ verified and that one is ✗ rejected,
in prose — no table here.
"""


def load_lanes():
    tmp = Path(tempfile.mkdtemp(prefix="lanes-rating-")) / "scripts"
    tmp.mkdir(parents=True)
    for name, body in STUBS.items():
        (tmp / f"{name}.py").write_text(body, encoding="utf-8")
    shutil.copy(SCRIPTS / "wiki_lint_lanes.py",
                tmp / "wiki_lint_lanes.py")
    spec = importlib.util.spec_from_file_location(
        "wiki_lint_lanes_rating_under_test",
        tmp / "wiki_lint_lanes.py")
    module = importlib.util.module_from_spec(spec)
    # The module resolves its siblings relative to its own
    # SCRIPTS dir (derived from ROOT); point it at the temp dir
    # by loading with the temp file location (spec path above).
    spec.loader.exec_module(module)
    return module


lanes = load_lanes()


class RatingLegendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rating-wiki-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "wiki").mkdir()

    def write_page(self, name, text):
        (self.tmp / "wiki" / name).write_text(text,
                                              encoding="utf-8")

    def test_table_without_legend_is_finding_with_line(self):
        self.write_page("ratings.md", NO_LEGEND_PAGE)
        result = lanes.rating_table_findings(self.tmp)
        self.assertEqual(result["count"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["page"], "wiki/ratings.md")
        self.assertEqual(finding["line"], 5)
        self.assertIn("★", finding["marks"])
        self.assertEqual(result["tables_with_marks"], 1)

    def test_table_with_legend_in_section_is_clean(self):
        self.write_page("ratings.md", WITH_LEGEND_PAGE)
        result = lanes.rating_table_findings(self.tmp)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["tables_with_marks"], 1)

    def test_legend_in_other_section_does_not_clear(self):
        self.write_page("ratings.md", LEGEND_ELSEWHERE_PAGE)
        result = lanes.rating_table_findings(self.tmp)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["findings"][0]["line"], 9)

    def test_plain_table_and_prose_marks_are_clean(self):
        self.write_page("data.md", PLAIN_TABLE_PAGE)
        self.write_page("notes.md", PROSE_MARKS_PAGE)
        result = lanes.rating_table_findings(self.tmp)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["tables_checked"], 1)
        self.assertEqual(result["tables_with_marks"], 0)


if __name__ == "__main__":
    unittest.main()
