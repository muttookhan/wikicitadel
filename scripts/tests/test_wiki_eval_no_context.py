#!/usr/bin/env python3
"""The --no_context control arm in wiki_eval_extended.py
(lane TA2; LongBench pattern).

Pins: a no-context answer scores correct only with every key
fact and no forbidden claim; an answerable question the arm
abstains on scores wrong while a no_answer question it abstains
on scores right; a no-context answer carrying citations is a
protocol violation and cannot score correct; the null answerer
(no answers file) is the floor — correct exactly on the
no_answer questions; and the arm aggregates separately from
the with-context run.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = load("wiki_eval_extended", "scripts/wiki_eval_extended.py")

ANSWERABLE = {"id": "Q1", "expected_abstain": False,
              "key_facts": ["forty two shelves"],
              "forbidden_claims": ["nine shelves"]}
NOANSWER = {"id": "Q2", "expected_abstain": True,
            "key_facts": [], "forbidden_claims": []}


class TestScoreNoContextAnswer(unittest.TestCase):
    def test_key_facts_correct(self):
        row = ev.score_no_context_answer(
            ANSWERABLE, {"id": "Q1",
                         "answer": "It keeps forty two shelves.",
                         "citations": []})
        self.assertTrue(row["correct"], row)

    def test_forbidden_claim_fails(self):
        row = ev.score_no_context_answer(
            ANSWERABLE, {"id": "Q1",
                         "answer": "Forty two shelves — formerly "
                                   "nine shelves.",
                         "citations": []})
        self.assertFalse(row["correct"])

    def test_citation_is_protocol_violation(self):
        row = ev.score_no_context_answer(
            ANSWERABLE, {"id": "Q1",
                         "answer": "It keeps forty two shelves.",
                         "citations": ["wiki/zarnok.md"]})
        self.assertTrue(row["cited_with_no_context"])
        self.assertFalse(row["correct"])

    def test_abstention_directions(self):
        self.assertFalse(ev.score_no_context_answer(
            ANSWERABLE, {"id": "Q1", "answer": "",
                         "abstained": True})["correct"])
        self.assertTrue(ev.score_no_context_answer(
            NOANSWER, {"id": "Q2", "answer": "",
                       "abstained": True})["correct"])
        self.assertFalse(ev.score_no_context_answer(
            NOANSWER, {"id": "Q2", "answer": "It is blue.",
                       "abstained": False})["correct"])


class TestArmAggregates(unittest.TestCase):
    def test_null_answerer_is_the_floor(self):
        arm = ev.no_context_arm([ANSWERABLE, NOANSWER], None)
        self.assertEqual(arm["accuracy"], 0.5)
        self.assertEqual(arm["answerable_accuracy"], 0.0)
        self.assertEqual(arm["no_answer_accuracy"], 1.0)
        self.assertIn("null answerer", arm["answerer"])

    def test_answers_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.jsonl"
            p.write_text(json.dumps(
                {"kind": "header", "set": "x"}) + "\n" +
                json.dumps({"id": "Q1", "answer": "forty two "
                            "shelves", "citations": []}) + "\n",
                encoding="utf-8")
            answers = ev.load_no_context_answers(p)
        self.assertEqual(set(answers), {"Q1"})
        arm = ev.no_context_arm([ANSWERABLE, NOANSWER], answers)
        self.assertEqual(arm["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
