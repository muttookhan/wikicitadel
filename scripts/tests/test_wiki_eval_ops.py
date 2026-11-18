#!/usr/bin/env python3
"""Operation-level eval scoring — HaluMem (lane TA2).

Pins scripts/wiki_eval_ops.py: each operation (create / update
/ delete / answer) is scored by its own rule — an update that
leaves the superseded value in place FAILS, a delete whose
subject resurfaces FAILS — the per-operation table aggregates
separately, and an answer error depending on a failed
create/update is counted as PROPAGATED (born upstream), the
HaluMem finding this scorer exists to surface. Also pins the
--from-results conversion of extended-eval rows into answer
operations.

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


ops_mod = load("wiki_eval_ops", "scripts/wiki_eval_ops.py")


def op(id_, operation, expected, observed, **kw):
    rec = {"id": id_, "operation": operation,
           "expected": expected, "observed": observed}
    rec.update(kw)
    return rec


class TestOperationRules(unittest.TestCase):
    def test_create_ok_and_missing_fact(self):
        good = op("1", "create", {"present": True,
                                  "key_facts": ["forty two"]},
                  {"present": True,
                   "text": "It keeps forty two shelves."})
        bad = op("2", "create", {"present": True,
                                 "key_facts": ["forty two"]},
                 {"present": True, "text": "It keeps shelves."})
        self.assertTrue(ops_mod.score_create(good)[0])
        self.assertFalse(ops_mod.score_create(bad)[0])

    def test_update_with_old_value_remaining_fails(self):
        rec = op("1", "update",
                 {"key_facts": ["Visa"],
                  "forbidden_facts": ["Mastercard"]},
                 {"text": "Primary card: Visa (Mastercard kept "
                          "as backup)."})
        self.assertFalse(ops_mod.score_update(rec)[0])
        clean = op("2", "update",
                   {"key_facts": ["Visa"],
                    "forbidden_facts": ["Mastercard"]},
                   {"text": "Primary card: Visa."})
        self.assertTrue(ops_mod.score_update(clean)[0])

    def test_delete_resurfaced_fails(self):
        rec = op("1", "delete", {"present": False},
                 {"present": False, "text": ""})
        self.assertTrue(ops_mod.score_delete(rec)[0])
        ghost = op("2", "delete", {"present": False},
                   {"present": True, "text": "still here"})
        self.assertFalse(ops_mod.score_delete(ghost)[0])

    def test_answer_abstention_and_forbidden(self):
        ok = op("1", "answer", {"abstain": True},
                {"text": "", "abstained": True})
        self.assertTrue(ops_mod.score_answer(ok)[0])
        stale = op("2", "answer",
                   {"key_facts": ["reserved"],
                    "forbidden_facts": ["seat is open"]},
                   {"text": "The seat is open.",
                    "abstained": False})
        self.assertFalse(ops_mod.score_answer(stale)[0])


class TestTableAndPropagation(unittest.TestCase):
    def test_per_operation_table_and_propagation(self):
        ops = [
            op("C1", "create", {"present": True,
                                "key_facts": ["alpha"]},
               {"present": True, "text": "nothing stored"}),
            op("A1", "answer", {"key_facts": ["alpha"]},
               {"text": "unknown", "abstained": False},
               depends_on=["C1"]),
            op("A2", "answer", {"key_facts": ["beta"]},
               {"text": "unknown", "abstained": False}),
            op("U1", "update", {"key_facts": ["gamma"],
                                "forbidden_facts": []},
               {"text": "gamma", "abstained": False}),
        ]
        report = ops_mod.score_ops(ops)
        self.assertEqual(report["by_operation"]["create"]
                         ["accuracy"], 0.0)
        self.assertEqual(report["by_operation"]["update"]
                         ["accuracy"], 1.0)
        self.assertEqual(report["answer_errors"]
                         ["propagated_from_create_update"], 1)
        self.assertEqual(report["answer_errors"]
                         ["born_at_answer"], 1)

    def test_unknown_operation_scores_wrong_not_crash(self):
        report = ops_mod.score_ops(
            [op("X", "teleport", {}, {})])
        self.assertEqual(report["correct_total"], 0)


class TestFromResults(unittest.TestCase):
    def test_extended_rows_convert(self):
        data = {"per_question": [
            {"id": "EQ-1", "must_in_topk": True},
            {"id": "EQ-2", "must_in_topk": False},
            {"id": "EQ-3", "top1_score": 0.1},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            ops = ops_mod.ops_from_results(p)
        report = ops_mod.score_ops(ops)
        self.assertEqual(report["by_operation"]["answer"]
                         ["operations"], 3)
        self.assertEqual(report["by_operation"]["answer"]
                         ["correct"], 2)


if __name__ == "__main__":
    unittest.main()
