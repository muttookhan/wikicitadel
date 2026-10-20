#!/usr/bin/env python3
"""Tests for scripts/wiki_predict.py (consolidated-queue
item 32 — preregistration prediction lines).

Pins, on fixture registers/results in a temp dir:
  - the hash chain: appends chain (prev_hash/line_hash as in
    wiki_checkpoint.py) and verify_chain detects a tampered
    line;
  - the refuse-after-results rule: `add` refuses when a
    results file carries the exact label the prediction
    names as its run, and when subject results are dated
    after the prediction date; earlier results (the
    baseline) are allowed;
  - scoring: appends a score line (the prediction line is
    never edited), folds to status scored with the metrics
    read from the results file; double-scoring, an unknown
    id and a bad verdict all refuse;
  - open_predictions (the eval runner's read path) returns
    only open predictions, filtered by subject key, and
    degrades to [] on a missing register.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wp = _load("wiki_predict")

TODAY = date(2030, 10, 20)


def results_file(dirpath, label, generated_at, metrics=True):
    doc = {"label": label, "generated_at": generated_at}
    if metrics:
        doc["aggregates"] = {
            "citation_coverage": {"@10": 0.94},
            "hit_rate_topk": 0.94,
            "mrr_must_cite": 0.73,
        }
        doc["abstention"] = {"abstention_rate": 0.5}
    p = Path(dirpath) / f"{label}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.register = self.root / "predictions.jsonl"
        self.results = self.root / "results"
        self.results.mkdir()

    def add(self, **kw):
        kw.setdefault("subject", "Next extended-eval run")
        kw.setdefault("prediction", "coverage@10 in [0.92, 0.96]")
        kw.setdefault("basis", "baseline on file")
        kw.setdefault("subject_key", "extended-eval")
        kw.setdefault("on", TODAY)
        kw.setdefault("path", self.register)
        kw.setdefault("results_dir", self.results)
        return wp.add_prediction(**kw)


class TestChain(Fixture):
    def test_appends_chain_and_verifies(self):
        self.add()
        self.add(prediction="MRR up")
        ok, idx, problem = wp.verify_chain(self.register)
        self.assertTrue(ok, problem)
        self.assertIsNone(idx)
        _h, lines = wp.load_register(self.register)
        self.assertEqual(lines[0]["prev_hash"], wp.GENESIS_PREV)
        self.assertEqual(lines[1]["prev_hash"], lines[0]["line_hash"])

    def test_tamper_breaks_chain(self):
        line = self.add()
        raw = self.register.read_text(encoding="utf-8")
        self.register.write_text(
            raw.replace("coverage@10 in", "coverage@10 NOT in"),
            encoding="utf-8")
        ok, idx, problem = wp.verify_chain(self.register)
        self.assertFalse(ok)
        self.assertEqual(idx, 0)
        self.assertIn("line_hash", problem)
        self.assertNotEqual(line["line_hash"], "")


class TestRefusals(Fixture):
    def test_named_run_results_refuse(self):
        results_file(self.results, "extended-post-phase3",
                     "2030-10-19T00:00:00+00:00")
        with self.assertRaises(ValueError) as cm:
            self.add(results_hint="extended-post-phase3")
        self.assertIn("already exist", str(cm.exception))

    def test_future_dated_results_refuse(self):
        future = (TODAY + timedelta(days=1)).isoformat()
        results_file(self.results, "extended-later",
                     f"{future}T00:00:00+00:00")
        with self.assertRaises(ValueError) as cm:
            self.add()
        self.assertIn("hindsight", str(cm.exception))

    def test_earlier_baseline_results_allowed(self):
        results_file(self.results, "extended-baseline-2030-10-20",
                     "2030-10-20T07:37:34+00:00")
        results_file(self.results, "extended-older",
                     "2030-10-19T00:00:00+00:00")
        line = self.add(results_hint="extended-post-phase3")
        self.assertEqual(line["id"], "pred-0001")
        self.assertEqual(line["results_hint"],
                         "extended-post-phase3")


class TestScoring(Fixture):
    def test_score_folds_and_extracts_metrics(self):
        line = self.add()
        rf = results_file(self.results, "extended-post-phase3",
                          "2030-10-21T00:00:00+00:00")
        score = wp.score_prediction(
            line["id"], str(rf), "confirmed", "landed in band",
            on=date(2030, 10, 21), path=self.register)
        self.assertEqual(score["metrics"]["citation_coverage@10"],
                         0.94)
        self.assertEqual(score["metrics"]["abstention_rate"], 0.5)
        _h, lines = wp.load_register(self.register)
        states = wp.fold(lines)
        self.assertEqual(states[0]["status"], "scored")
        self.assertEqual(states[0]["score"]["verdict"],
                         "confirmed")
        # the prediction line itself was never edited
        pred_line = [l for l in lines
                     if l.get("kind") == "prediction"][0]
        self.assertNotIn("outcome", pred_line)
        ok, _i, problem = wp.verify_chain(self.register)
        self.assertTrue(ok, problem)

    def test_double_score_refuses(self):
        line = self.add()
        rf = results_file(self.results, "extended-post-phase3",
                          "2030-10-21T00:00:00+00:00")
        wp.score_prediction(line["id"], str(rf), "mixed", "part",
                             path=self.register)
        with self.assertRaises(ValueError):
            wp.score_prediction(line["id"], str(rf), "mixed",
                                "again", path=self.register)

    def test_unknown_id_and_bad_verdict_refuse(self):
        rf = results_file(self.results, "extended-x",
                          "2030-10-20T00:00:00+00:00")
        with self.assertRaises(ValueError):
            wp.score_prediction("pred-9999", str(rf), "mixed",
                                "n/a", path=self.register)
        line = self.add()
        with self.assertRaises(ValueError):
            wp.score_prediction(line["id"], str(rf), "probably",
                                "n/a", path=self.register)
        with self.assertRaises(ValueError):
            wp.score_prediction(line["id"], str(self.root / "nope.json"),
                                "mixed", "n/a", path=self.register)


class TestOpenPredictions(Fixture):
    def test_open_only_and_key_filter(self):
        a = self.add()
        self.add(subject="A gateway change",
                 subject_key="gateway-change",
                 prediction="promotions blocked fall")
        rf = results_file(self.results, "extended-post-phase3",
                          "2030-10-21T00:00:00+00:00")
        wp.score_prediction(a["id"], str(rf), "refuted", "moved",
                            path=self.register)
        open_all = wp.open_predictions(self.register)
        self.assertEqual([s["subject_key"] for s in open_all],
                         ["gateway-change"])
        self.assertEqual(
            wp.open_predictions(self.register, "extended-eval"),
            [])

    def test_missing_register_degrades(self):
        self.assertEqual(
            wp.open_predictions(self.root / "absent.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
