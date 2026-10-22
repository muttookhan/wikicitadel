#!/usr/bin/env python3
"""Tests for scripts/wiki_meta_benchmark.py (W3 meta-benchmark
+ preregistered criteria).

Fixture ledgers are built through the harness's OWN append
path (wiki_bakeoff.append_to_ledger over synthetic run
records whose aggregates are computed by the instruments'
own aggregation functions), so the judge's recompute check
runs against a ledger that genuinely verifies — and a
tampered run file genuinely fails it.
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


meta = _load("wiki_meta_benchmark", "wiki_meta_benchmark.py")
bakeoff = meta.bakeoff


def _rows(prefix, ranks):
    rows = []
    for i, rank in enumerate(ranks):
        scorer = {"id": f"{prefix}-{i + 1:03d}",
                  "must_cite_rank": rank,
                  "hit_in_topk": rank is not None and rank <= 10,
                  "must_in_topk": rank is not None and rank <= 10,
                  "precision_at_k": 0.1}
        rows.append({**scorer, "top3": [], "scorer_row": scorer})
    return rows


def fake_run(name, spec, golden, sup, cq001_rank, battery):
    g = _rows("GQ", golden)
    e = _rows("EQ", golden)
    s = _rows("ED", sup)
    c = _rows("CQ", golden)
    run = {
        "kind": "bakeoff-run", "version": 1,
        "label": f"bakeoff-{name}",
        "config": {"name": name, "spec": spec,
                   "reranker_note": None},
        "corpus": {"git_head": "deadbeef", "dirty": False,
                   "docs": 3, "scope": "wiki/"},
        "generated_at": "2026-10-22T00:00:00-04:00",
        "instruments": {
            "golden": {"aggregates":
                       bakeoff.aggregate_bench_rows(g),
                       "per_question": g},
            "extended": {"aggregates": bakeoff.ext.aggregates(
                [r["scorer_row"] for r in e]),
                "per_question": e},
            "supersession": {"aggregates": bakeoff.ext
                             .aggregates(
                                 [r["scorer_row"] for r in s]),
                             "per_question": s},
            "conflict": {"aggregates":
                         bakeoff.aggregate_bench_rows(c),
                         "per_question": c,
                         "cq001_must_cite_rank": cq001_rank},
        },
        "battery": battery,
        "aggregates": bakeoff.aggregate_bench_rows(g),
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
        "latencyMs": {"metric": "median latency",
                      "value": triple["latencyMs"]},
        "contextTokens": {"metric": "median context",
                          "value": triple["contextTokens"]},
    }
    run["row_identity"] = bakeoff.row_identity(run)
    return run


BATTERY_OK = {"applicable": True, "tau": 1.23, "cases": 12,
              "passed": 12, "all_pass": True, "coverage": {}}
BATTERY_9 = {"applicable": True, "tau": 1.23, "cases": 12,
             "passed": 9, "all_pass": False, "coverage": {}}
BATTERY_NA = {"applicable": False, "note": "not hybrid"}

FIXTURE_CRITERIA = [
    {"id": "golden-full", "instrument": "golden",
     "metric": "summaries.golden.aggregates."
               "citation_coverage.@10",
     "op": ">=", "threshold": 1.0,
     "applies_to": "all-configurations",
     "rationale": "fixture", "rule_source": "fixture"},
    {"id": "battery-full",
     "instrument": "abstention battery",
     "metric": "summaries.battery.passed_fraction",
     "op": ">=", "threshold": 1.0,
     "applies_to": "hybrid-family",
     "rationale": "fixture", "rule_source": "fixture"},
    {"id": "cq001-retrievable", "instrument": "conflict",
     "metric": "summaries.conflict.cq001_must_cite_rank",
     "op": "not-null", "threshold": None,
     "applies_to": "all-configurations",
     "rationale": "fixture", "rule_source": "fixture"},
]


def build_ledger(td, runs):
    ledger = td / "bakeoff-ledger.jsonl"
    for name, run in runs:
        (td / f"run-{name}.json").write_text(
            json.dumps(run), encoding="utf-8")
        bakeoff.append_to_ledger(run, f"run-{name}.json",
                                 ledger)
    return ledger


def standard_runs():
    return [
        ("passer", fake_run(
            "passer", dict(bakeoff.CONFIGS["house"]),
            [1, 2, 1, 3], [1, 2, None, 1], 2, BATTERY_OK)),
        ("battery-failer", fake_run(
            "battery-failer", dict(bakeoff.CONFIGS[
                "cross-encoder"]),
            [1, 1, 2, 1], [1, 1, 2, 1], 2, BATTERY_9)),
        ("plain-bm25", fake_run(
            "plain-bm25", dict(bakeoff.CONFIGS["bm25-plain"]),
            [2, 1, 1, 3], [2, 1, 1, None], 8, BATTERY_NA)),
    ]


class MetaBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.td = Path(self._tmp.name)
        self._real_root = bakeoff.ROOT
        bakeoff.ROOT = self.td
        self.criteria = self.td / "criteria.jsonl"
        self.verdicts = self.td / "verdicts.jsonl"

    def tearDown(self):
        bakeoff.ROOT = self._real_root
        self._tmp.cleanup()

    def _register_and_freeze(self):
        meta.register_set(self.criteria, "test-set", 1,
                          FIXTURE_CRITERIA, "2026-10-22",
                          "test", "fixture timing")
        meta.freeze_set(self.criteria, "test-set", 1,
                        "2026-10-22")

    def test_judge_refuses_unfrozen_set(self):
        meta.register_set(self.criteria, "test-set", 1,
                          FIXTURE_CRITERIA, "2026-10-22",
                          "test", "fixture timing")
        ledger = build_ledger(self.td, standard_runs())
        with self.assertRaises(meta.Refusal):
            meta.judge(ledger, self.criteria, self.verdicts,
                       "test-set", 1, "2026-10-22")

    def test_versions_are_immutable_amendments_mint_new(self):
        self._register_and_freeze()
        with self.assertRaises(meta.Refusal):
            meta.register_set(self.criteria, "test-set", 1,
                              FIXTURE_CRITERIA, "2026-10-22",
                              "test", "again")
        with self.assertRaises(meta.Refusal):
            meta.register_set(self.criteria, "test-set", 2,
                              FIXTURE_CRITERIA, "2026-10-22",
                              "test", "amends nothing",
                              amends=99)
        entry = meta.register_set(
            self.criteria, "test-set", 2, FIXTURE_CRITERIA,
            "2026-10-22", "test", "amendment", amends=1)
        self.assertEqual(entry["amends"], 1)

    def test_freeze_binds_criteria_against_tampering(self):
        self._register_and_freeze()
        lines = self.criteria.read_text(
            encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["criteria"][0]["threshold"] = 0.5
        lines[0] = json.dumps(first, ensure_ascii=False)
        self.criteria.write_text("\n".join(lines) + "\n",
                                 encoding="utf-8")
        ledger = build_ledger(self.td, standard_runs())
        with self.assertRaises(meta.Refusal):
            meta.judge(ledger, self.criteria, self.verdicts,
                       "test-set", 1, "2026-10-22")

    def test_verdicts_measure_and_gate(self):
        self._register_and_freeze()
        ledger = build_ledger(self.td, standard_runs())
        out = meta.judge(ledger, self.criteria, self.verdicts,
                         "test-set", 1, "2026-10-22")
        by_name = {v["row"]["config"]: v
                   for v in out["verdicts"]}
        self.assertTrue(by_name["passer"]["adoptable"])
        self.assertTrue(
            by_name["passer"]["row_recomputes"])
        failer = by_name["battery-failer"]
        self.assertFalse(failer["adoptable"])
        bat = next(r for r in failer["results"]
                   if r["criterion"] == "battery-full")
        self.assertEqual(bat["status"], "fail")
        self.assertEqual(bat["measured"], 0.75)
        bm = by_name["plain-bm25"]
        bat = next(r for r in bm["results"]
                   if r["criterion"] == "battery-full")
        self.assertEqual(bat["status"], "not-applicable")
        self.assertTrue(bm["adoptable"])
        # determinism: a second judging appends nothing, and
        # judging into a fresh register reproduces the bytes
        out2 = meta.judge(ledger, self.criteria, self.verdicts,
                          "test-set", 1, "2026-10-22")
        self.assertEqual(out2["verdicts"], [])
        self.assertEqual(len(out2["skipped_already_judged"]),
                         3)
        fresh = self.td / "verdicts2.jsonl"
        meta.judge(ledger, self.criteria, fresh,
                   "test-set", 1, "2026-10-22")
        self.assertEqual(
            fresh.read_bytes(), self.verdicts.read_bytes())

    def test_tampered_run_file_flags_the_row(self):
        self._register_and_freeze()
        runs = standard_runs()
        ledger = build_ledger(self.td, runs)
        run = json.loads((self.td / "run-passer.json")
                         .read_text(encoding="utf-8"))
        run["instruments"]["golden"]["per_question"][0][
            "must_cite_rank"] = 9
        (self.td / "run-passer.json").write_text(
            json.dumps(run), encoding="utf-8")
        out = meta.judge(ledger, self.criteria, self.verdicts,
                         "test-set", 1, "2026-10-22")
        by_name = {v["row"]["config"]: v
                   for v in out["verdicts"]}
        self.assertFalse(by_name["passer"]["row_recomputes"])
        self.assertFalse(by_name["passer"]["adoptable"])
        self.assertTrue(by_name["passer"]
                        ["recompute_findings"])
        self.assertTrue(
            by_name["battery-failer"]["row_recomputes"])

    def test_meta_discrimination_and_coverage(self):
        self._register_and_freeze()
        runs = standard_runs()
        ledger = build_ledger(self.td, runs)
        meta.judge(ledger, self.criteria, self.verdicts,
                   "test-set", 1, "2026-10-22")
        extra = fake_run("unjudged",
                         dict(bakeoff.CONFIGS["house"]),
                         [1, 1, 1, 1], [1, 1, 1, 1], 1,
                         BATTERY_OK)
        (self.td / "run-unjudged.json").write_text(
            json.dumps(extra), encoding="utf-8")
        bakeoff.append_to_ledger(extra, "run-unjudged.json",
                                 ledger)
        view = meta.meta_view(ledger, self.criteria,
                              self.verdicts)
        group = view["groups"][0]
        stats = group["criteria_stats"]
        self.assertIn("NON-DISCRIMINATING",
                      stats["golden-full"]["discrimination"])
        self.assertEqual(stats["battery-full"]
                         ["discrimination"], "discriminates")
        self.assertEqual(
            [r["config"] for r in view["unjudged_rows"]],
            ["unjudged"])
        self.assertEqual(view["rows_judged_any_version"], 3)

    def test_verify_registers_round_trip_and_tamper(self):
        self._register_and_freeze()
        ledger = build_ledger(self.td, standard_runs())
        meta.judge(ledger, self.criteria, self.verdicts,
                   "test-set", 1, "2026-10-22")
        ok, findings = meta.verify_registers(
            self.criteria, self.verdicts, ledger)
        self.assertTrue(ok, findings)
        lines = self.verdicts.read_text(
            encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["adoptable"] = not first["adoptable"]
        lines[0] = json.dumps(first, ensure_ascii=False)
        self.verdicts.write_text("\n".join(lines) + "\n",
                                 encoding="utf-8")
        ok, findings = meta.verify_registers(
            self.criteria, self.verdicts, ledger)
        self.assertFalse(ok)
        self.assertTrue(findings)


class HouseAdoptionV1Tests(unittest.TestCase):
    def test_v1_codifies_the_four_standing_rules(self):
        crit = {c["id"]: c
                for c in meta.HOUSE_ADOPTION_V1}
        self.assertEqual(
            sorted(crit),
            ["battery-full-pass", "cq001-must-cite-"
             "retrievable", "golden-full-coverage",
             "supersession-floor"])
        meta.validate_criteria(meta.HOUSE_ADOPTION_V1)
        self.assertEqual(
            crit["golden-full-coverage"]["threshold"], 1.0)
        self.assertEqual(
            crit["battery-full-pass"]["applies_to"],
            "hybrid-family")
        self.assertEqual(
            crit["battery-full-pass"]["metric"],
            "summaries.battery.passed_fraction")
        self.assertEqual(
            crit["supersession-floor"]["threshold"], 0.75)
        self.assertEqual(
            crit["cq001-must-cite-retrievable"]["op"],
            "not-null")
        for c in meta.HOUSE_ADOPTION_V1:
            self.assertTrue(c["rule_source"])
        self.assertIn("AFTER the eight bakeoff ledger rows",
                      meta.V1_TIMING)


if __name__ == "__main__":
    unittest.main()
