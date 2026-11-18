#!/usr/bin/env python3
"""Tests for scripts/wiki_memscore.py (Marathon R2 lane B2).

The honesty contract is the point: a field the result file does
not carry comes back as None (rendered "not recorded"), never an
invented number; the triple is never collapsed into a composite.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ms = _load("wiki_memscore")

FULL = {
    "label": "run-full",
    "aggregates": {"citation_coverage": {"@10": 0.9},
                   "mrr_must_cite": 0.5},
    "latencyMs": 123.5,
    "contextTokens": 4096,
}
ACCURACY_ONLY = {
    "label": "run-plain",
    "aggregates": {"citation_coverage": {"@1": 0.1, "@10": 0.93},
                   "mrr_must_cite": 0.42},
    "corpus_docs": 71,
}


class TestMemScore(unittest.TestCase):
    def test_present_fields_reported_verbatim(self):
        run = ms.memscore(FULL, "full.json")
        self.assertEqual(run["accuracy"], 0.9)
        self.assertEqual(run["accuracy_metric"], "coverage@10")
        self.assertEqual(run["latencyMs"], 123.5)
        self.assertEqual(run["contextTokens"], 4096)

    def test_absent_fields_are_none_never_invented(self):
        run = ms.memscore(ACCURACY_ONLY, "plain.json")
        self.assertEqual(run["accuracy"], 0.93)
        self.assertIsNone(run["latencyMs"])
        self.assertIsNone(run["contextTokens"])
        table = ms.render_markdown([run])
        self.assertIn("not recorded", table)

    def test_no_composite_is_ever_produced(self):
        for fixture in (FULL, ACCURACY_ONLY):
            run = ms.memscore(fixture, "x.json")
            self.assertNotIn("score", run)
            self.assertNotIn("composite", run)
            self.assertNotIn("memscore", run)

    def test_headline_fallback_names_its_metric(self):
        run = ms.memscore({"label": "pk", "passk_rate": 0.75}, "pk.json")
        self.assertEqual(run["accuracy"], 0.75)
        self.assertIn("passk_rate", run["accuracy_metric"])

    def test_repro_pack_yields_one_triple_per_engine(self):
        pack = {"label": "pack", "kind": "reproducible-benchmark-pack",
                "results": {
                    "hybrid": {"citation_coverage": {"@10": 1.0},
                               "mrr_must_cite": 0.6},
                    "bm25": {"citation_coverage": {"@10": 0.9},
                             "mrr_must_cite": 0.5}}}
        runs = ms.extract_runs(pack, "pack.json")
        self.assertEqual([r["label"] for r in runs],
                         ["pack/bm25", "pack/hybrid"])
        self.assertEqual(runs[0]["accuracy"], 0.9)
        self.assertIsNone(runs[0]["latencyMs"])

    def test_scale_bench_latency_stays_not_recorded_with_note(self):
        bench = {"kind": "scale-bench", "label": "scale",
                 "rows": [{"docs": 100, "median_ms": 4.7}]}
        run = ms.memscore(bench, "scale-bench.json")
        self.assertIsNone(run["latencyMs"])
        self.assertIn("per-size", run["notes"])

    def test_existing_result_shapes_parse(self):
        # Every real file in evaluation/results/ must yield a
        # triple whose accuracy is present or honestly None.
        results = ROOT / "evaluation" / "results"
        files = sorted(results.glob("*.json"))
        self.assertTrue(files)
        for path in files:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            for run in ms.extract_runs(data, path.name):
                self.assertIn("accuracy", run)
                self.assertIn("latencyMs", run)
                self.assertIn("contextTokens", run)


if __name__ == "__main__":
    unittest.main()
