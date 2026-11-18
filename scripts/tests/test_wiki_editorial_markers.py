#!/usr/bin/env python3
"""Tests for the editorial-marker census in
scripts/wiki_lint_lanes.py (Lane 5, continued) —
consolidated queue item 15, 2030-10-20.

The markers are statement-level editorial flags in a page's
prose: {{cite}} (needs a citation it lacks), {{clarify}}
(unclear as written), {{disputed}} (under dispute). The
census counts them by kind with locations, under the
corpus's standing reading rules: fenced code and inline
code never yield a marker, the frontmatter is not prose,
and the compiled layer's exclusions (filings, talk, index,
log) apply.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_lanes_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_lint_lanes_markers_under_test",
        SCRIPTS / "wiki_lint_lanes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lanes = load_lanes_module()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


FM = ("---\ntitle: Fixture\ntype: source\n"
      "created: 2030-10-20\nupdated: 2030-10-20\n"
      "sources:\n  - raw/sources/fixture.md\n"
      "tags: [fixture]\n---\n\n")


class MarkerCensusFixtureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root
        _write(root / "wiki/sources/marked.md", FM +
               "# Marked\n\n"
               "This claim has no source. {{cite}}\n\n"
               "This sentence could mean two things. {{clarify}}\n\n"
               "The two sources disagree here. {{disputed}}\n\n"
               "Two on one line: {{cite}} and {{cite}} again.\n")
        _write(root / "wiki/sources/codey.md", FM +
               "# Codey\n\n"
               "The convention is written `{{cite}}` in backticks.\n\n"
               "```\n"
               "A fenced example: {{clarify}} {{disputed}}\n"
               "```\n\n"
               "Prose again, nothing flagged.\n")
        _write(root / "wiki/sources/frontmatter.md",
               "---\ntitle: Fixture {{cite}}\ntype: source\n"
               "created: 2030-10-20\nupdated: 2030-10-20\n"
               "sources: []\ntags: [fixture]\n---\n\n"
               "# Frontmatter\n\nNo markers in the body.\n")
        _write(root / "wiki/filings/not-counted.md", FM +
               "# Filing\n\nFilings are excluded. {{cite}}\n")
        _write(root / "wiki/sources/plain.md", FM +
               "# Plain\n\nNothing to flag.\n")
        cls.result = lanes.editorial_markers(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_counts_by_kind(self):
        # marked.md: cite x3 (one line carries two), clarify
        # x1, disputed x1. codey.md and frontmatter.md add
        # none; the filing is excluded.
        self.assertEqual(self.result["counts"],
                         {"cite": 3, "clarify": 1, "disputed": 1})
        self.assertEqual(self.result["total"], 5)

    def test_locations_carry_page_line_kind(self):
        locs = self.result["locations"]
        self.assertEqual(len(locs), 5)
        for loc in locs:
            self.assertEqual(loc["page"], "wiki/sources/marked.md")
            self.assertIn(loc["kind"],
                          ("cite", "clarify", "disputed"))
            self.assertGreaterEqual(loc["line"], 1)
            self.assertIn("{{", loc["excerpt"])
        kinds_by_line = {}
        for loc in locs:
            kinds_by_line.setdefault(loc["line"], []).append(
                loc["kind"])
        # The two-on-one-line case yields two cite locations.
        self.assertIn(["cite", "cite"],
                      list(kinds_by_line.values()))

    def test_deterministic_order(self):
        keys = [(h["page"], h["line"], h["kind"])
                for h in self.result["locations"]]
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
