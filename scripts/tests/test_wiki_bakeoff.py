#!/usr/bin/env python3
"""Tests for scripts/wiki_bakeoff.py (W3 uniform harness).

The load-bearing test is the divergence check: this harness's
golden aggregates for the house configuration must EQUAL
wiki_rerank.compare_rerankers' own output for the coverage
reranker — the harness calls the instruments' scorers, so any
difference is a harness defect, not a second opinion.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bakeoff = _load("wiki_bakeoff", "wiki_bakeoff.py")
ws = bakeoff.ws
bench = bakeoff.bench
rerank = bakeoff.rerank


def fake_run(name="fake"):
    """A minimal run record with the shapes verify recomputes
    from — no corpus involved."""
    rows = [{"id": "GQ-001", "must_cite_rank": 1,
             "hit_in_topk": True, "must_in_topk": True,
             "precision_at_k": 0.1, "top3": ["wiki/a.md"],
             "scorer_row": {"id": "GQ-001", "must_cite_rank": 1,
                            "hit_in_topk": True,
                            "must_in_topk": True,
                            "precision_at_k": 0.1}}]
    agg = bakeoff.aggregate_bench_rows(rows)
    run = {
        "kind": "bakeoff-run", "version": 1,
        "label": f"bakeoff-{name}",
        "config": {"name": name, "spec": dict(bakeoff.CONFIGS["house"]),
                   "reranker_note": None},
        "corpus": {"git_head": "deadbeef", "dirty": False,
                   "docs": 3, "scope": "wiki/"},
        "generated_at": "2026-10-22T00:00:00-04:00",
        "instruments": {
            "golden": {"aggregates": agg, "per_question": rows},
            "extended": {"aggregates": agg, "per_question": rows},
            "supersession": {"aggregates": agg,
                             "per_question": rows},
            "conflict": {"aggregates": agg, "per_question": rows,
                         "cq001_must_cite_rank": None},
        },
        "battery": {"applicable": False,
                    "note": "test double"},
        "aggregates": agg,
        "latencyMs": 12.5,
        "contextTokens": 42,
        "measurements": {
            "latency": {"per_question_ms": [10.0, 15.0],
                        "median_ms": 12.5},
            "context_tokens": {"per_question": [40, 44],
                               "median": 42},
        },
    }
    triple = bakeoff.memscore_mod.memscore(run, source=run["label"])
    run["memscore"] = {
        "accuracy": {"metric": "golden citation coverage@10",
                     "value": triple["accuracy"],
                     "percent": 100.0},
        "latencyMs": {"metric": "median per-question retrieval "
                                "latency (ms)",
                      "value": triple["latencyMs"]},
        "contextTokens": {"metric": "median packed-evidence "
                                    "context (tokens)",
                          "value": triple["contextTokens"]},
    }
    run["row_identity"] = bakeoff.row_identity(run)
    return run


class MemScoreShapeTests(unittest.TestCase):
    def test_memscore_reads_the_run_shape(self):
        run = fake_run()
        triple = bakeoff.memscore_mod.memscore(run, source="x")
        self.assertEqual(triple["accuracy"], 1.0)
        self.assertEqual(triple["accuracy_metric"], "coverage@10")
        self.assertEqual(triple["latencyMs"], 12.5)
        self.assertEqual(triple["contextTokens"], 42)

    def test_identity_ignores_latency_and_timestamp(self):
        run = fake_run()
        ident = run["row_identity"]
        run["generated_at"] = "2030-01-01T00:00:00-04:00"
        run["latencyMs"] = 999.0
        run["measurements"]["latency"] = {
            "per_question_ms": [999.0], "median_ms": 999.0}
        run["memscore"]["latencyMs"]["value"] = 999.0
        self.assertEqual(bakeoff.row_identity(run), ident)


class LedgerTests(unittest.TestCase):
    def test_append_only_chain_and_verify(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            real_root = bakeoff.ROOT
            bakeoff.ROOT = td
            try:
                ledger = td / "ledger.jsonl"
                run1 = fake_run("one")
                run2 = fake_run("two")
                (td / "run-one.json").write_text(
                    json.dumps(run1), encoding="utf-8")
                (td / "run-two.json").write_text(
                    json.dumps(run2), encoding="utf-8")
                e1 = bakeoff.append_to_ledger(run1, "run-one.json",
                                              ledger)
                before = ledger.read_bytes()
                e2 = bakeoff.append_to_ledger(run2, "run-two.json",
                                              ledger)
                after = ledger.read_bytes()
                # append-only: the first entry's bytes are a
                # strict prefix of the grown ledger
                self.assertTrue(after.startswith(before))
                self.assertEqual(e2["prev_entry_sha256"],
                                 e1["entry_sha256"])
                ok, findings = bakeoff.verify_ledger(ledger)
                self.assertTrue(ok, findings)
            finally:
                bakeoff.ROOT = real_root

    def test_verify_detects_a_tampered_figure(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            real_root = bakeoff.ROOT
            bakeoff.ROOT = td
            try:
                ledger = td / "ledger.jsonl"
                run = fake_run("one")
                path = td / "run-one.json"
                path.write_text(json.dumps(run), encoding="utf-8")
                bakeoff.append_to_ledger(run, "run-one.json",
                                          ledger)
                run["instruments"]["golden"]["per_question"][0][
                    "must_cite_rank"] = 7
                path.write_text(json.dumps(run), encoding="utf-8")
                ok, findings = bakeoff.verify_ledger(ledger)
                self.assertFalse(ok)
                self.assertTrue(findings)
            finally:
                bakeoff.ROOT = real_root


class RunnerShapeTests(unittest.TestCase):
    def test_battery_not_applicable_off_hybrid(self):
        runner = bakeoff.ConfigRunner.__new__(
            bakeoff.ConfigRunner)
        runner.spec = dict(bakeoff.CONFIGS["bm25-plain"])
        out = bakeoff.run_battery(runner)
        self.assertFalse(out["applicable"])
        self.assertIn("hybrid", out["note"])

    def test_aggregate_formula(self):
        rows = [
            {"must_cite_rank": 1, "hit_in_topk": True,
             "precision_at_k": 0.5},
            {"must_cite_rank": None, "hit_in_topk": False,
             "precision_at_k": 0.0},
            {"must_cite_rank": 4, "hit_in_topk": True,
             "precision_at_k": 0.25},
        ]
        agg = bakeoff.aggregate_bench_rows(rows)
        self.assertEqual(agg["citation_coverage"]["@1"], 0.3333)
        self.assertEqual(agg["citation_coverage"]["@10"], 0.6667)
        self.assertEqual(agg["mrr_must_cite"], round(
            (1.0 + 0.25) / 3, 4))


class DivergenceTests(unittest.TestCase):
    """The harness must agree with the instruments' own CLI
    machinery on the same configuration."""

    def test_house_golden_matches_compare_rerankers(self):
        docs = ws.collect_docs("wiki")
        adj = ws.build_link_graph(docs)
        questions = bakeoff.load_questions(
            bakeoff.INSTRUMENT_FILES["golden"])
        built = rerank.build_compare_rerankers(ws, ["coverage"])
        theirs = rerank.compare_rerankers(
            ws, bench, docs, adj, questions, built)["models"]["coverage"]
        runner = bakeoff.ConfigRunner("house", docs, adj)
        mine, _rows, _lat = bakeoff.run_bench_instrument(
            runner, questions)
        for key in ("citation_coverage", "hit_rate_topk",
                    "mean_precision_at_k", "mrr_must_cite"):
            self.assertEqual(mine[key], theirs[key],
                             f"golden {key}: harness {mine[key]} "
                             f"!= compare {theirs[key]}")
        self.assertEqual(mine["questions"],
                         theirs["questions_scored"])


if __name__ == "__main__":
    unittest.main()
