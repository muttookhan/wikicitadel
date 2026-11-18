#!/usr/bin/env python3
"""Tests for the path/username shape classes in
scripts/wiki_leak_lint.py (B3 governance round).

Pins:
  - a planted absolute home path (/home/<user>/, /Users/<user>/,
    C:\\Users\\<user>\\) in a filings fixture is flagged as
    absolute-home-path, reported by class + file + line number
    only — the planted username appears NOWHERE in the JSON
    rendering of the findings;
  - a bare-username path shape (~<user>/…, relative
    home/<user>/…) is flagged as bare-username-in-path;
  - a clean fixture is silent for both classes;
  - both classes are baselinable through the SAME baseline
    mechanism as the existing baselinable classes: an audited
    baseline built from the planted scan makes the finding
    stop surfacing as new.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent


def load_leak_module():
    """Import wiki_leak_lint; when the gateway package is not
    present beside the scratch copy (a minimal lane scratch),
    stub scan_secrets with an empty result — the path-shape
    classes under test are local to the lint and never touch
    the gateway scanner."""
    if not (REPO / "tools" / "gateway" / "gateway"
            / "defense.py").is_file() \
            and "gateway.defense" not in sys.modules:
        gw = types.ModuleType("gateway")
        defense = types.ModuleType("gateway.defense")
        defense.scan_secrets = lambda text: {"findings": []}
        gw.defense = defense
        sys.modules["gateway"] = gw
        sys.modules["gateway.defense"] = defense
    spec = importlib.util.spec_from_file_location(
        "wiki_leak_lint_under_test", SCRIPTS / "wiki_leak_lint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


leak = load_leak_module()

PLANTED = "planteduser42"
CLEAN_PAGE = "# Clean\n\nA relative link: wiki/sources/page.md\n"
PLANTED_PAGE = ("# Note\n\nSome prose.\n\n"
                f"The file lives at /home/{PLANTED}/wiki/page.md\n")


class PathShapeScanTests(unittest.TestCase):
    def test_absolute_home_shapes(self):
        for text in (f"/home/{PLANTED}/x.md",
                     f"/Users/{PLANTED}/x.md",
                     f"C:\\Users\\{PLANTED}\\x.md"):
            hits = {h["pattern"]: h["count"]
                    for h in leak.scan_path_shapes(text)}
            self.assertEqual(hits.get("absolute-home-path"), 1, text)
            self.assertNotIn("bare-username-in-path", hits, text)

    def test_bare_username_shapes(self):
        for text in (f"~{PLANTED}/x.md",
                     f"home/{PLANTED}/x.md", f"Users/{PLANTED}/x.md"):
            hits = {h["pattern"]: h["count"]
                    for h in leak.scan_path_shapes(text)}
            self.assertEqual(hits.get("bare-username-in-path"), 1, text)

    def test_clean_text_is_silent(self):
        for text in (CLEAN_PAGE, "plain prose, no paths at all",
                     "/home/ and /Users/ with no user segment",
                     "wiki/sources/page.md, raw/filings/a.md",
                     # A bare ~/ names no user (it is the writer's own
                     # home, unnamed) — the corpus's house style for
                     # home-relative paths must stay silent:
                     f"~/{PLANTED}/x.md", "~/workspace/llm-wiki/wiki/x.md",
                     "~/MEMORY.md", "~/memory/people/a.md"):
            self.assertEqual(leak.scan_path_shapes(text), [], text)

    def test_scan_text_merges_path_shapes(self):
        hits = {h["pattern"] for h in leak.scan_text(PLANTED_PAGE)}
        self.assertIn("absolute-home-path", hits)


class FilingsSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="leak-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        area = self.tmp / "raw" / "filings"
        area.mkdir(parents=True)
        (area / "planted.md").write_text(PLANTED_PAGE,
                                         encoding="utf-8")
        (area / "clean.md").write_text(CLEAN_PAGE, encoding="utf-8")

    def test_planted_flagged_by_class_file_and_line_only(self):
        surface = leak.scan_filings(self.tmp)
        hits = [f for f in surface["findings"]
                if f["pattern"] == "absolute-home-path"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["file"], "raw/filings/planted.md")
        self.assertEqual(hits[0]["count"], 1)
        lines = [lf for lf in surface["line_findings"]
                 if lf["pattern"] == "absolute-home-path"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["line"], 5)
        # The discipline: the matched text is never quoted —
        # the planted username appears nowhere in the report.
        self.assertNotIn(PLANTED, json.dumps(surface))

    def test_clean_fixture_silent(self):
        root = self.tmp / "cleanroot"
        area = root / "wiki" / "filings"
        area.mkdir(parents=True)
        (area / "only.md").write_text(CLEAN_PAGE, encoding="utf-8")
        surface = leak.scan_filings(root)
        shapes = [f for f in surface["findings"]
                  if f["pattern"] in ("absolute-home-path",
                                      "bare-username-in-path")]
        self.assertEqual(shapes, [])

    def test_path_shapes_baseline_through_same_mechanism(self):
        surfaces = [leak.scan_filings(self.tmp)]
        self.assertIn("absolute-home-path",
                      leak.BASELINABLE_PATTERNS)
        self.assertIn("bare-username-in-path",
                      leak.BASELINABLE_PATTERNS)
        payload = leak.build_baseline(surfaces, "2026-10-20")
        fps = [fp for fp in payload["fingerprints"]
               if fp["pattern"] == "absolute-home-path"]
        self.assertEqual(len(fps), 1)
        self.assertNotIn(PLANTED, json.dumps(payload))
        baseline_path = self.tmp / "baseline.json"
        baseline_path.write_text(json.dumps(payload),
                                 encoding="utf-8")
        baseline = leak.load_baseline(baseline_path)
        fresh = [leak.scan_filings(self.tmp)]
        leak.annotate_baseline(fresh, baseline)
        self.assertEqual(fresh[0]["new_total"], 0)
        self.assertEqual(fresh[0]["baselined_total"], 1)


if __name__ == "__main__":
    unittest.main()
