#!/usr/bin/env python3
"""Tests for the leaderboard-axes + directional-slice extension of
scripts/wiki_eval_extended.py (Marathon R2 lane B2). No dedicated
test module for this runner existed before this lane.

Covers: the closed axis vocabulary (valid tags kept in vocabulary
order, unknown tags surfaced via invalid_axes, never dropped
silently), per-question rows carrying axes/slice through scoring,
and an end-to-end run over a fixture set asserting by_axis /
by_slice land in the result JSON.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ev = _load("wiki_eval_extended")


class TestAxes(unittest.TestCase):
    def test_valid_tags_kept_in_vocabulary_order(self):
        q = {"id": "X-1", "axes": ["privacy", "governance"]}
        self.assertEqual(ev.question_axes(q), ["governance", "privacy"])

    def test_untagged_is_a_valid_outcome(self):
        self.assertEqual(ev.question_axes({"id": "X-2"}), [])
        self.assertEqual(ev.question_axes({"id": "X-3", "axes": []}), [])

    def test_unknown_tags_surfaced_not_dropped(self):
        qs = [{"id": "X-4", "axes": ["governance", "speed"]},
              {"id": "X-5", "axes": ["safety"]}]
        self.assertEqual(ev.invalid_axes(qs), {"X-4": ["speed"]})
        self.assertEqual(ev.question_axes(qs[0]), ["governance"])

    def test_score_row_carries_axes_and_slice(self):
        q = {"id": "X-6", "class": "temporal", "slice": "directional",
             "axes": ["governance"], "must_cite": ["wiki/a.md"]}
        ranked = [(1.0, "wiki/a.md"), (0.5, "wiki/b.md")]
        row = ev.score_answerable(q, ranked, 10)
        self.assertEqual(row["axes"], ["governance"])
        self.assertEqual(row["slice"], "directional")
        self.assertTrue(row["must_in_topk"])


class TestEndToEnd(unittest.TestCase):
    def test_fixture_run_reports_by_axis_and_by_slice(self):
        questions = ev.load_questions(ev.QUESTIONS)
        fixture = [q for q in questions
                   if q.get("slice") == "directional"][:2]
        tagged = [q for q in questions if q.get("axes")][:2]
        picked = {q["id"]: q for q in fixture + tagged}
        self.assertTrue(picked, "extended set carries no axes/slice fixtures")
        tmp = ROOT / "evaluation" / "results" / "_axes_fixture.jsonl"
        out_label = "_axes_fixture_run"
        try:
            tmp.write_text("\n".join(json.dumps(q) for q in picked.values())
                           + "\n", encoding="utf-8")
            rc = ev.main(["wiki_eval_extended.py", "--questions", str(tmp),
                          "--label", out_label])
            self.assertEqual(rc, 0)
            result = json.loads(
                (ROOT / "evaluation" / "results" / f"{out_label}.json")
                .read_text(encoding="utf-8"))
            if fixture:
                self.assertIn("directional", result["by_slice"])
                self.assertEqual(
                    result["by_slice"]["directional"]["questions"],
                    len(fixture))
            if tagged:
                self.assertTrue(result["by_axis"])
            self.assertEqual(result["axes_invalid"], {})
        finally:
            tmp.unlink(missing_ok=True)
            (ROOT / "evaluation" / "results" / f"{out_label}.json").unlink(
                missing_ok=True)


if __name__ == "__main__":
    unittest.main()
