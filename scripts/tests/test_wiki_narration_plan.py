#!/usr/bin/env python3
"""Tests for scripts/wiki_narration_plan.py (gap-15 remainder, TB8 row 5).

Pins: a plan is DATA — shot list + narration script + asset
manifest; one shot and one needed asset per section; durations
estimated at the audio brief's 150 wpm with the per-shot floor;
the plan states on its face that no media was generated and no
external call was made; the narration text is the sections'
speakable prose (markdown stripped via the audio-brief machinery).

Run:  python3 -m unittest discover -s scripts/tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_narration_plan  # noqa: E402

PAGE = """---
title: "Plan Page"
type: concept
---

# Plan Page

Welcome to the plan page introduction words here.

## First Section

The first section explains **the thing** in detail with a
[[other-page|link]] included for context.

## Second Section

Short closer.
"""


class TestNarrationPlan(unittest.TestCase):
    def build(self, td):
        p = Path(td) / "page.md"
        p.write_text(PAGE, encoding="utf-8")
        return wiki_narration_plan.plan_for_page(p, root=Path(td))

    def test_plan_shape(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self.build(td)
        self.assertEqual(plan["format"], "narration-plan/1")
        self.assertEqual(plan["title"], "Plan Page")
        self.assertEqual(len(plan["shots"]), 3)
        self.assertEqual(len(plan["assets"]), 3)
        self.assertEqual(
            [s["section"] for s in plan["shots"]],
            ["Opening", "First Section", "Second Section"])

    def test_no_media_no_calls_stated(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self.build(td)
        self.assertFalse(plan["generated_media"])
        self.assertEqual(plan["external_calls"], [])
        self.assertIn("No image, video or audio is generated",
                      plan["note"])

    def test_assets_needed_and_linked(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self.build(td)
        for shot, asset in zip(plan["shots"], plan["assets"]):
            self.assertEqual(shot["asset_ref"], asset["asset_id"])
            self.assertEqual(asset["for_shot"], shot["shot_id"])
            self.assertEqual(asset["status"], "needed")

    def test_durations(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self.build(td)
        self.assertEqual(plan["reading_speed_wpm"], 150)
        for shot in plan["shots"]:
            self.assertGreaterEqual(
                shot["est_seconds"],
                wiki_narration_plan.SECONDS_PER_SHOT_FLOOR)
        self.assertEqual(
            plan["est_total_seconds"],
            sum(s["est_seconds"] for s in plan["shots"]))

    def test_narration_is_speakable(self):
        with tempfile.TemporaryDirectory() as td:
            plan = self.build(td)
        self.assertIn("the thing", plan["narration_script"])
        self.assertNotIn("**", plan["narration_script"])
        self.assertNotIn("[[", plan["narration_script"])


if __name__ == "__main__":
    unittest.main()
