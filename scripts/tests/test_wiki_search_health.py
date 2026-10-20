#!/usr/bin/env python3
"""Tests for scripts/wiki_search_health.py — search-health
filing (item 45).

Fixture layer only: toy evaluation artefacts (golden + extended
+ conflict run JSONs, a retrieval baseline with one zero-result
and one thin-result probe, a three-case battery, a three-line
Ask log) through the metric computation, the named-miss and
weakest-class extraction, and the delta machinery (no previous
filing -> baseline; a previous filing with embedded metrics ->
a real delta).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_health():
    spec = importlib.util.spec_from_file_location(
        "wiki_search_health", SCRIPTS / "wiki_search_health.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wiki_search_health"] = module
    spec.loader.exec_module(module)
    return module


health = load_health()
AS_OF = date(2030, 10, 20)


def run_json(questions, cov10, mrr, per_question, by_class=None,
             label="run", set_name=None):
    rec = {"label": label, "generated_at": "2030-10-20T00:00:00+00:00",
           "aggregates": {"questions": questions,
                          "citation_coverage": {"@1": 0.1, "@10": cov10},
                          "hit_rate_topk": 0.75,
                          "mrr_must_cite": mrr},
           "per_question": per_question}
    if set_name:
        rec["set"] = set_name
    if by_class:
        rec["by_class"] = by_class
    return rec


def build_toy(root: Path):
    results = root / "evaluation" / "results"
    results.mkdir(parents=True)
    (root / "wiki" / "access").mkdir(parents=True)
    (root / "wiki" / "filings").mkdir(parents=True)
    golden = run_json(15, 0.9333, 0.5,
                      [{"id": "GQ-1", "must_in_topk": False}],
                      label="golden-run")
    (results / "golden-run.json").write_text(json.dumps(golden))
    extended = run_json(
        4, 0.5, 0.4,
        [{"id": "EQ-1", "must_in_topk": False},
         {"id": "EQ-2", "must_in_topk": True}],
        by_class={
            "weak": {"questions": 2,
                     "citation_coverage": {"@10": 0.0},
                     "mrr_must_cite": 0.1, "hit_rate_topk": 0.5},
            "strong": {"questions": 2,
                       "citation_coverage": {"@10": 1.0},
                       "mrr_must_cite": 0.9, "hit_rate_topk": 1.0}},
        label="extended-latest", set_name="extended")
    (results / "extended-latest.json").write_text(json.dumps(extended))
    conflict = run_json(12, 0.8333, 0.4675, [],
                        label="conflict-slice-toy")
    (results / "conflict-slice-toy.json").write_text(json.dumps(conflict))
    baseline = {"per_query": {
        "ZQ": {"result_count": 0, "question": "nothing here",
               "top10": []},
        "TQ": {"result_count": 3, "question": "thin one", "top10": []},
        "NQ": {"result_count": 500, "question": "normal", "top10": []}}}
    (root / "evaluation" / "retrieval-baseline.json").write_text(
        json.dumps(baseline))
    cases = [
        {"kind": "header", "set": "abstention-battery"},
        {"kind": "case", "id": "AB-1", "mode": "search",
         "case_kind": "no_evidence", "expected_verdict": "abstain"},
        {"kind": "case", "id": "AB-2", "mode": "search",
         "case_kind": "no_evidence", "expected_verdict": "abstain"},
        {"kind": "case", "id": "AB-3", "mode": "candidates",
         "case_kind": "severed_only", "expected_verdict": "abstain"},
        {"kind": "case", "id": "AB-4", "mode": "record",
         "case_kind": "record", "expected_verdict": "hold"},
    ]
    (root / "evaluation" / "abstention-battery.jsonl").write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n")
    qa = [
        {"id": "q1", "status": "answered", "citations": ["a"]},
        {"id": "q2", "status": "answered", "citations": ["a", "b"]},
        {"id": "q3", "status": "abstained", "citations": []},
    ]
    (root / "wiki" / "access" / "qa-2030.jsonl").write_text(
        "\n".join(json.dumps(q) for q in qa) + "\n")
    return root


class HealthFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = build_toy(Path(cls._tmp.name))
        cls.h = health.compute_health(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_zero_and_thin_probes_named(self):
        self.assertEqual([e["id"] for e in self.h["zero_probes"]],
                         ["ZQ"])
        self.assertEqual([e["id"] for e in self.h["thin_probes"]],
                         ["TQ"])
        self.assertEqual(self.h["metrics"]["zero_result_probes"], 1)
        self.assertEqual(self.h["metrics"]["thin_result_probes"], 1)

    def test_weakest_class_and_named_misses(self):
        self.assertEqual(self.h["extended"]["weakest"][0]["class"],
                         "weak")
        self.assertEqual(self.h["extended"]["misses"], ["EQ-1"])
        self.assertEqual(self.h["golden"]["misses"], ["GQ-1"])
        self.assertEqual(self.h["metrics"]["golden_coverage@10"],
                         0.9333)
        self.assertEqual(self.h["metrics"]["conflict_mrr"], 0.4675)

    def test_battery_search_side_only(self):
        self.assertEqual(self.h["battery"]["search_cases"], 3)
        self.assertEqual(self.h["battery"]["by_kind"],
                         {"no_evidence": 2, "severed_only": 1})

    def test_qa_rates(self):
        qa = self.h["qa"]
        self.assertEqual(qa["questions"], 3)
        self.assertEqual(qa["abstentions"], 1)
        self.assertAlmostEqual(qa["abstention_rate"], 1 / 3)
        self.assertEqual(qa["distinct_citations"], 2)

    def test_delta_baseline_then_real(self):
        self.assertIsNone(health.previous_metrics(self.root, AS_OF))
        text = health.render(self.h, None, AS_OF)
        self.assertIn("No previous filing — baseline", text)
        prev = dict(self.h["metrics"])
        prev["golden_coverage@10"] = 0.8
        (self.root / "wiki" / "filings"
         / "search-health-2030-10-19.md").write_text(
            "<!-- search-health-metrics: "
            + json.dumps(prev) + " -->\n", encoding="utf-8")
        got = health.previous_metrics(self.root, AS_OF)
        self.assertEqual(got["golden_coverage@10"], 0.8)
        text = health.render(self.h, got, AS_OF)
        self.assertIn("| golden_coverage@10 | 0.8 | 0.9333 |", text)


if __name__ == "__main__":
    unittest.main()
