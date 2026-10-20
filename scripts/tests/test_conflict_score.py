#!/usr/bin/env python3
"""ISE scoring for the conflict slice.

Pins scripts/wiki_conflict_score.py's deterministic rules on
fixture slice questions + fixture answers: Identify via governing
citation or superseded-form naming, Solve via key facts + not
presenting the superseded form as current (with the quoted-to-
correct exception), surface-both replacing Solve for the
unresolved kind, and Escalate scored only where applicable.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scorer = load("wiki_conflict_score", "scripts/wiki_conflict_score.py")

REVERSAL = {
    "id": "CQ-T1", "conflict_kind": "reversal",
    "question": "Is the seat reserved or open?",
    "key_facts": ["OPEN", "2030-10-16"],
    "must_cite": ["wiki/filings/galen-filings.md"],
    "acceptable_cites": ["wiki/syntheses/decisions-record.md"],
    "forbidden_claims": ["the seat stays RESERVED"],
    "superseded_form": "the seat stays RESERVED (original form)",
}
UNRESOLVED = {
    "id": "CQ-T2", "conflict_kind": "unresolved",
    "question": "When did the demo project launch?",
    "key_facts": ["March 18, 2030", "March 17, 2030"],
    "must_cite": ["wiki/sources/demo-project-export.md"],
    "acceptable_cites": [],
    "forbidden_claims": [],
    "superseded_form": "(none)",
    "must_surface_both": ["March 18, 2030", "March 17, 2030"],
}


class TestScorer(unittest.TestCase):
    def test_good_reversal_answer_scores_full(self):
        row = scorer.score_answer(REVERSAL, {
            "answer": "The seat is OPEN (owner ruling, 2030-10-16); "
                      "the reserved form was superseded.",
            "citations": ["filings/galen-filings"],
        })
        self.assertEqual((row["identify"], row["solve"]), (1, 1))
        self.assertIsNone(row["escalate"])

    def test_dead_form_presented_as_current_fails_both(self):
        row = scorer.score_answer(REVERSAL, {
            "answer": "The seat stays RESERVED, per the record.",
            "citations": [],
        })
        self.assertEqual((row["identify"], row["solve"]), (0, 0))

    def test_dead_form_quoted_to_correct_is_not_a_solve_failure(self):
        row = scorer.score_answer(REVERSAL, {
            "answer": "OPEN since 2030-10-16. The earlier form — "
                      "'the seat stays RESERVED' — was superseded.",
            "citations": [],
        })
        self.assertEqual(row["identify"], 1)
        self.assertEqual(row["solve"], 1)

    def test_citation_by_bare_stem_identifies(self):
        row = scorer.score_answer(REVERSAL, {
            "answer": "OPEN, 2030-10-16.",
            "citations": ["galen-filings"],
        })
        self.assertEqual(row["identify"], 1)

    def test_unresolved_both_dates_and_open_scores_full(self):
        row = scorer.score_answer(UNRESOLVED, {
            "answer": "The export contradicts itself: March 18, "
                      "2030 in one shard, March 17, 2030 in "
                      "another. The question is unresolved; both "
                      "stand as recorded.",
            "citations": ["sources/demo-project-export"],
        })
        self.assertEqual(
            (row["identify"], row["solve"], row["escalate"]),
            (1, 1, 1))

    def test_unresolved_picking_one_date_fails(self):
        row = scorer.score_answer(UNRESOLVED, {
            "answer": "The demo project launched on March 17, 2030.",
            "citations": [],
        })
        self.assertEqual(row["solve"], 0)
        self.assertEqual(row["escalate"], 0)

    def test_prominence_is_manual_never_scored(self):
        row = scorer.score_answer(REVERSAL, {
            "answer": "OPEN, 2030-10-16.", "citations": []})
        self.assertIsNone(row["identify_prominence"])

    def test_slice_file_loads(self):
        # A fixture slice in the real file's shape (header line +
        # one JSON object per question): the loader splits the
        # header from the questions and keeps every row.
        import json
        import tempfile
        rows = [{"kind": "header", "set": "conflict",
                 "version": 1}]
        for i in range(12):
            rows.append({
                "id": "CQ-F%02d" % i, "class": "conflict",
                "conflict_kind": ("unresolved" if i % 3 == 0
                                  else "reversal"),
                "question": "Fixture question %d?" % i})
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "conflict-questions.jsonl"
            path.write_text(
                "".join(json.dumps(r) + "\n" for r in rows),
                encoding="utf-8")
            header, questions = scorer.load_slice(path)
        self.assertEqual(header["set"], "conflict")
        self.assertEqual(len(questions), 12)
        self.assertTrue(all(q["class"] == "conflict"
                            for q in questions))
        kinds = {q["conflict_kind"] for q in questions}
        self.assertIn("unresolved", kinds)
        self.assertIn("reversal", kinds)


if __name__ == "__main__":
    unittest.main()
