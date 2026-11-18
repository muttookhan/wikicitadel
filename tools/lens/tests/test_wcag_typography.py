"""Build-list W2 (2026-10-22) — WCAG typography assertions.

Covers wcag_gate.typography_results() on fixture stylesheets
(clean + violating), on the REAL tree assets (where one row pins
a recorded finding: the reading paragraph spacing misses the
§1.4.8 strict reading — the gate reports it, this test keeps it
visible until the owner rules on the stylesheet), and the BDA
Comfort preset's exact values + wiring in the source assets
(the preset itself shipped with item 64 in Phase 8; this lane
verifies and gates it, it does not re-add it).

Run from anywhere:
    python3 -m unittest tools.lens.tests.test_wcag_typography
    python3 tools/lens/tests/test_wcag_typography.py
"""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))

import wcag_gate as WG  # noqa: E402

ASSETS = LENS_DIR / "assets"

CLEAN_CSS = """
body { font-size: 16px; line-height: 1.55; }
.reading-body p, .reading-body li { font-size: 16px; line-height: 1.65; }
.reading-body p { margin: 18px 0; }
.reading-body table { overflow-x: auto; }
.reading-body pre { overflow-x: auto; }
.reading-body figure.page-figure img { max-width: 100%; height: auto; }
@media (max-width: 820px) {
  #app { grid-template-columns: 1fr; }
  #rail { display: none; }
}
@media print {
  body { background: #fff; color: #111; }
  #rail, #inspector { display: none !important; }
  #canvas { max-height: none; overflow: visible; }
}
"""

CLEAN_JS = """
const READ_PRESETS = [
  { id: "comfort-bda", name: "Comfort (BDA)", font: "sans-serif",
    size: 19, lh: 2.0, measure: 62, ls: "0.35ch", ws: "1.225ch",
    bg: "#F5EFE0", lig: "none" },
];
"""

BAD_CSS = """
body { font-size: 16px; line-height: 1.55; min-width: 900px; }
.reading-body p { font-size: 16px; line-height: 22px; margin: 4px 0;
                  white-space: nowrap; }
.x { letter-spacing: 0.1em !important; }
.reading-body table { border-collapse: collapse; }
"""

BAD_JS = "const READ_PRESETS = [];\n"


def by_name(results):
    return {name: ok for _level, name, ok, _detail in results}


class CleanFixture(unittest.TestCase):
    def test_every_assertion_passes(self):
        rows = by_name(WG.typography_results(CLEAN_CSS, CLEAN_JS))
        failing = [n for n, ok in rows.items() if not ok]
        self.assertEqual(failing, [],
                         f"clean fixture should pass every row: {failing}")
        # 2 (§1.4.8) + 3 (§1.4.12) + 4 (proxies) + 4 (print) + 2 (presets)
        self.assertEqual(len(rows), 15)


class ViolatingFixture(unittest.TestCase):
    def test_each_violation_is_caught(self):
        rows = by_name(WG.typography_results(BAD_CSS, BAD_JS))
        expected_failures = [
            "reading-surface line-height >= 1.5 (§1.4.8)",
            "reading paragraph spacing >= 1.5x line spacing (§1.4.8)",
            "no !important on text-spacing properties (§1.4.12, inspected)",
            "no white-space: nowrap in the reading body (§1.4.12, inspected)",
            "reading line-heights relative, not fixed px (§1.4.12, inspected)",
            "PROXY no min-width on html/body (§1.4.10 reflow)",
            "PROXY narrow-viewport single-column restack (§1.4.10 reflow)",
            "PROXY wide reading content scrolls internally (§1.4.10 reflow)",
            "PROXY reading images fluid (§1.4.10 reflow)",
            "print template present (print template)",
            "Comfort (BDA) reading preset shipped (build-list W2)",
            "all shipped reading presets keep measure <= 80ch (§1.4.8)",
        ]
        for name in expected_failures:
            self.assertIn(name, rows)
            self.assertFalse(rows[name], f"should fail: {name}")

    def test_missing_app_js_is_a_finding_not_a_skip(self):
        rows = by_name(WG.typography_results(CLEAN_CSS, None))
        self.assertFalse(
            rows["Comfort (BDA) reading preset shipped (build-list W2)"])


class RealTree(unittest.TestCase):
    """The shipped assets against the assertions. Exactly one row
    is expected to fail: the §1.4.8 paragraph-spacing reading
    (collapsed margin 10px vs the 15.6px the strict reading
    requires at 16px/1.65) — a finding the gate prints for the
    owner. If the stylesheet is ever fixed, this pin must be
    updated in the same change; that is the point of pinning it."""

    @classmethod
    def setUpClass(cls):
        cls.rows = by_name(WG.typography_results(
            (ASSETS / "lens.css").read_text(encoding="utf-8"),
            (ASSETS / "app.js").read_text(encoding="utf-8")))

    def test_comfort_preset_aa_passes(self):
        self.assertTrue(
            self.rows["Comfort (BDA) reading preset shipped (build-list W2)"])

    def test_paragraph_spacing_finding_is_pinned(self):
        self.assertFalse(self.rows[
            "reading paragraph spacing >= 1.5x line spacing (§1.4.8)"])

    def test_everything_else_passes(self):
        others = {n: ok for n, ok in self.rows.items()
                  if "paragraph spacing" not in n}
        failing = [n for n, ok in others.items() if not ok]
        self.assertEqual(failing, [])


class ComfortPresetSource(unittest.TestCase):
    """The preset in the source assets: exact BDA values, the
    five pre-existing presets untouched beside it (purely
    additive), and every --read-* variable the profile setter
    writes actually consumed by the stylesheet."""

    @classmethod
    def setUpClass(cls):
        cls.js = (ASSETS / "app.js").read_text(encoding="utf-8")
        cls.css = (ASSETS / "lens.css").read_text(encoding="utf-8")

    def test_six_presets_incl_comfort(self):
        arr = re.search(r"READ_PRESETS\s*=\s*\[(.*?)\];", self.js, re.S)
        ids = re.findall(r'id:\s*"([^"]+)"', arr.group(1))
        self.assertEqual(sorted(ids), sorted([
            "inter-loose", "fraunces-standard", "atkinson-standard",
            "inter-airy", "fraunces-compact", "comfort-bda"]))

    def test_comfort_values_exact(self):
        obj = re.search(r"\{[^{}]*comfort-bda[^{}]*\}", self.js).group(0)
        self.assertIn('ls: "0.35ch"', obj)
        self.assertIn('ws: "1.225ch"', obj)
        self.assertIn('lig: "none"', obj)
        self.assertIn('bg: "#F5EFE0"', obj)
        self.assertEqual(float(re.search(r"lh:\s*([\d.]+)", obj).group(1)),
                         2.0)

    def test_profile_variables_are_consumed(self):
        for var in ("--read-font", "--read-size", "--read-lh",
                    "--read-measure", "--read-ls", "--read-ws",
                    "--read-lig", "--read-bg"):
            self.assertIn(f"var({var}", self.css,
                          f"{var} is set by the profile but never "
                          "consumed by lens.css")


if __name__ == "__main__":
    unittest.main()
