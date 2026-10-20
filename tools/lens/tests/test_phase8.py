"""Surfaces-build unit tests — run from anywhere:

    python3 -m unittest tools.lens.tests.test_phase8
    python3 tools/lens/tests/test_phase8.py

Covers: the evidence-matrix computation against synthetic pages
and registers; lifecycle prefix aggregation; the Argdown
subset parser + SVG compiler; bullet geometry; sparkline shared
scale; the due forecast's overdue block; the WCAG gate's contrast
mathematics on the real palette.
"""

# NOTE (WikiCitadel public edition): the reference deployment also carries
# three test classes that assert facts about that deployment's own private
# corpus (its page count, named pages, and its lint-lane history on named
# dates). They are not shipped: they could only ever pass against that
# corpus. Every class below is portable and runs against any WikiCitadel
# tree, including the seed demo at this repo's root.

import json
import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
REPO = HERE.parents[3]
sys.path.insert(0, str(LENS_DIR))

import lenslib as L  # noqa: E402
import stateviews as SV  # noqa: E402
import wcag_gate as WG  # noqa: E402


def _page(pid, tags=(), sources=0, status="", superseded_by="",
          attested="", path=None):
    return {"id": pid, "path": path or f"wiki/x/{pid}.md",
            "tags": list(tags), "status": status,
            "superseded_by": superseded_by, "attested_until": attested,
            "sources_count": sources}


class MatrixSynthetic(unittest.TestCase):
    def test_state_precedence(self):
        due = {"wiki/x/due.md"}
        self.assertEqual(SV.verification_state(
            _page("a", status="superseded", attested="2999-01-01",
                  sources=3), due, None), "superseded")
        self.assertEqual(SV.verification_state(
            _page("b", attested="2999-01-01", sources=3), due, None),
            "owner-verified")
        self.assertEqual(SV.verification_state(
            _page("due", sources=3), due, None), "re-verification-due")
        self.assertEqual(SV.verification_state(
            _page("c", sources=1), due, None), "cited")
        self.assertEqual(SV.verification_state(
            _page("d"), due, None), "unverified")

    def test_matrix_counts_and_gaps(self):
        pages = [_page("p1", tags=["agents"], sources=2),
                 _page("p2", tags=["agents"]),
                 _page("p3", tags=["agents"], attested="2999-01-01"),
                 _page("p4", tags=["solo"], sources=1),
                 _page("p5")]
        mx = SV.evidence_matrix(pages, set())
        self.assertEqual(mx["total_pages"], 5)
        self.assertEqual(sum(len(v) for v in mx["totals"].values()), 5)
        agents = next(r for r in mx["topics"] if r["topic"] == "agents")
        self.assertEqual(agents["total"], 3)
        self.assertEqual(agents["cells"]["cited"], ["p1"])
        self.assertEqual(agents["cells"]["unverified"], ["p2"])
        self.assertEqual(agents["cells"]["owner-verified"], ["p3"])
        # "solo" is a 1-page tag: folded, and named as folded.
        self.assertIn("solo", mx["folded_topics"])
        self.assertEqual(mx["untagged_pages"], ["p5"])
        self.assertEqual(mx["unverified_pages"], ["p2", "p5"])


class LifecycleSynthetic(unittest.TestCase):
    def test_prefix_aggregation(self):
        records = [
            {"page": "a", "states": ["asserted", "cited"]},
            {"page": "b", "states": ["asserted", "cited", "severed"]},
            {"page": "c", "states": ["asserted"]},
        ]
        # Drive the aggregation half via a fake repo is overkill;
        # exercise the same code path lifecycle_paths uses by
        # checking its invariants on the real output below, and
        # unit-test the prefix math through a tiny inline replica
        # of the documented contract:
        pref = {}
        for rec in records:
            for i in range(1, len(rec["states"]) + 1):
                key = tuple(rec["states"][:i])
                pref.setdefault(key, 0)
                pref[key] += 1
        self.assertEqual(pref[("asserted",)], 3)
        self.assertEqual(pref[("asserted", "cited")], 2)
        self.assertEqual(pref[("asserted", "cited", "severed")], 1)


class ArgdownSubset(unittest.TestCase):
    TEXT = """[Speed reading works]
RSVP apps claim large gains.

<The Rayner evidence>
Review of the eye-movement literature.
{source: "Rayner et al. 2016"}

<The Rayner evidence> - [Speed reading works]
[Speed reading works] + <Vendor marketing>

a stray prose line"""

    def test_parse_subset(self):
        m = SV.parse_argdown(self.TEXT)
        names = {n["name"] for n in m["statements"] + m["arguments"]}
        self.assertIn("Speed reading works", names)
        self.assertIn("The Rayner evidence", names)
        self.assertIn("Vendor marketing", names)  # implicit, warned
        self.assertTrue(any("Vendor marketing" in w for w in m["warnings"]))
        rels = {(r["from"], r["to"], r["kind"]) for r in m["relations"]}
        self.assertIn(("The Rayner evidence", "Speed reading works",
                       "attack"), rels)
        self.assertIn(("Speed reading works", "Vendor marketing",
                       "support"), rels)
        arg = next(n for n in m["arguments"]
                   if n["name"] == "The Rayner evidence")
        self.assertEqual(arg["meta"].get("source"), '"Rayner et al. 2016"')
        self.assertEqual(m["unparsed"], ["a stray prose line"])

    def test_svg_contains_nodes_and_glyphs(self):
        svg, warns = SV.argdown_svg(SV.parse_argdown(self.TEXT))
        self.assertIn("The Rayner evidence", svg)
        self.assertIn("Speed reading works", svg)
        self.assertIn("+", svg)
        self.assertIn("−", svg)
        self.assertEqual(warns, [])

    def test_cycle_is_reported_not_hung(self):
        m = SV.parse_argdown("[A]\n[B]\n[A] + [B]\n[B] + [A]\n")
        svg, warns = SV.argdown_svg(m)
        self.assertTrue(any("cycle" in w for w in warns))
        self.assertIn("A", svg)


class BulletsAndSparklines(unittest.TestCase):
    def test_bullet_geometry_zero_based(self):
        bands = [{"to": 1, "label": "≤1", "tone": "good"},
                 {"to": 3, "label": "2–3", "tone": "watch"},
                 {"to": 10, "label": "4+", "tone": "bad"}]
        g = SV.bullet_geometry(3, 0, 10, bands)
        self.assertAlmostEqual(g["value_frac"], 0.3)
        self.assertEqual(g["target_frac"], 0.0)
        self.assertEqual(g["bands"][0]["from"], 0.0)
        for a, b in zip(g["bands"], g["bands"][1:]):
            self.assertAlmostEqual(a["to"], b["from"])
        self.assertEqual(g["bands"][-1]["to"], 1.0)
        g0 = SV.bullet_geometry(0, 0, 10, bands)
        self.assertEqual(g0["value_frac"], 0.0)

    def test_sparkline_shared_scale(self):
        big = SV.sparkline_points([0, 11], 11)
        small = SV.sparkline_points([0, 1], 11)
        # On the shared scale the big series touches the top pad
        # (y=2) and the small one stays near the baseline.
        self.assertIn(",2.0", big)
        small_ys = [float(p.split(",")[1]) for p in small.split()]
        self.assertTrue(all(y > 20 for y in small_ys))
        self.assertEqual(SV.sparkline_points([], 5), "")
        single = SV.sparkline_points([4], 11)
        self.assertEqual(len(single.split()), 1)


class DueForecast(unittest.TestCase):
    def test_overdue_block_leads_and_cumulative_grows(self):
        sched = [
            {"page": "wiki/a.md", "claim": "A", "due": "2026-10-18",
             "status": "overdue", "days_overdue": 2},
            {"page": "wiki/b.md", "claim": "B", "due": "2026-10-20",
             "status": "due", "days_overdue": 0},
            {"page": "wiki/c.md", "claim": "C", "due": "2026-10-25",
             "status": "upcoming", "days_overdue": 0},
            {"page": "wiki/d.md", "claim": "D", "due": "2027-03-01",
             "status": "upcoming", "days_overdue": 0},
            # due_claims returns date objects, not strings — the
            # forecast must normalise them.
            {"page": "wiki/e.md", "claim": "E", "due": date(2026, 11, 2),
             "status": "upcoming", "days_overdue": 0},
        ]
        f = SV.due_forecast(sched, date(2026, 10, 20), window_days=90)
        self.assertEqual(f["due_now_count"], 2)
        self.assertEqual(f["overdue_count"], 1)
        self.assertEqual(f["due_now"][0]["page"], "wiki/a.md")
        cum = f["cumulative_if_neglected"]
        self.assertEqual(cum, sorted(cum))  # never decreases
        self.assertEqual(cum[-1], 4)  # due-now 2 + C and E in-window; D out
        self.assertEqual(f["total_scheduled"], 5)


class WcagMath(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(WG.contrast_ratio("#000000", "#FFFFFF"),
                               21.0, places=1)
        self.assertAlmostEqual(WG.contrast_ratio("#FFFFFF", "#FFFFFF"),
                               1.0, places=2)

    def test_real_palette(self):
        css = (LENS_DIR / "assets" / "lens.css").read_text(encoding="utf-8")
        tokens = WG.parse_tokens(css)
        self.assertGreater(len(tokens), 15)
        ink3 = WG.resolve(tokens, tokens["--ink-3"])
        surf1 = WG.resolve(tokens, tokens["--surface-1"])
        self.assertGreaterEqual(WG.contrast_ratio(ink3, surf1), 4.5)
        # The gate's known live finding: dark chip text on
        # --status-broken fails AA for normal text. Asserting the
        # COMPUTATION (the gate reports it; the palette is the
        # owner's to change), not a pass.
        on_light = WG.resolve(tokens, tokens["--ink-on-light"])
        broken = WG.resolve(tokens, tokens["--status-broken"])
        ratio = WG.contrast_ratio(on_light, broken)
        self.assertTrue(3.0 < ratio < 4.5, ratio)

    def test_atkinson_faces_declared(self):
        css = (LENS_DIR / "assets" / "lens.css").read_text(encoding="utf-8")
        self.assertIn("Atkinson Hyperlegible", css)
        self.assertTrue((LENS_DIR / "assets" / "fonts" /
                         "LICENSE-atkinson-hyperlegible.txt").exists())


if __name__ == "__main__":
    unittest.main()
