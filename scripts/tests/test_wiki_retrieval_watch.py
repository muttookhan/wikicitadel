#!/usr/bin/env python3
"""Tests for scripts/wiki_retrieval_watch.py — retrieval
anomaly as a security signal (item 35).

Two layers: synthetic feature dicts through the pure detector
(a poisoned distribution trips the named signals; a clean one
is quiet), and a fixture corpus (the real script + the real
wiki_search.py copied into a temp root, per the house fixture
pattern) where a baseline is created cleanly and a stuffed
"poison" page added afterwards trips the watch for real.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_watch():
    spec = importlib.util.spec_from_file_location(
        "wiki_retrieval_watch", SCRIPTS / "wiki_retrieval_watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


watch = load_watch()
ROOT = watch.ROOT


def feats(result_count=20, top1="wiki/entities/a.md", share=0.2,
          conc=0.3, top10=None, new=None, top_collection=None):
    return {"result_count": result_count, "top1_path": top1,
            "top1_share": share, "concentration": conc,
            "top_collection": top_collection,
            "top10": top10 if top10 is not None else [top1],
            "new_in_top10": new or [],
            "question": "q", "origin": "golden"}


class FeatureTests(unittest.TestCase):
    def test_collection_key(self):
        self.assertEqual(watch.collection_key("wiki/sources/x.md"),
                         "wiki/sources")
        self.assertEqual(watch.collection_key("raw/filings/galen/y.md"),
                         "raw/filings")
        self.assertEqual(watch.collection_key("wiki/index.md"), "wiki")

    def test_query_features(self):
        from datetime import date
        ranked = [
            (10.0, ROOT / "wiki/entities/a.md", "t", {}),
            (5.0, ROOT / "wiki/sources/b.md", "t", {}),
            (5.0, ROOT / "wiki/sources/c.md", "t", {}),
        ]
        f = watch.query_features(ranked, {}, date(2030, 10, 20))
        self.assertEqual(f["result_count"], 3)
        self.assertEqual(f["top1_path"], "wiki/entities/a.md")
        self.assertAlmostEqual(f["top1_share"], 0.5)
        self.assertAlmostEqual(f["concentration"], 2 / 3, places=3)

    def test_query_features_new_page_window(self):
        from datetime import date
        ranked = [(10.0, ROOT / "wiki/entities/new.md", "t", {})]
        seen = {"wiki/entities/new.md": "2030-10-18"}
        f = watch.query_features(ranked, seen, date(2030, 10, 20))
        self.assertEqual(f["new_in_top10"], ["wiki/entities/new.md"])
        seen_old = {"wiki/entities/new.md": "2030-09-01"}
        f2 = watch.query_features(ranked, seen_old, date(2030, 10, 20))
        self.assertEqual(f2["new_in_top10"], [])


class DetectorTests(unittest.TestCase):
    def baseline(self, per_query, wins):
        return {"created": "2030-10-19", "per_query": per_query,
                "aggregate": {"probes": len(per_query),
                              "median_result_count": 20,
                              "top1_wins": wins,
                              "intrusion_pages": []}}

    def test_clean_is_quiet(self):
        q = {f"GQ-{i:03d}": feats() for i in range(1, 16)}
        agg = {"probes": 15, "median_result_count": 20,
               "top1_wins": {"wiki/entities/a.md": 15},
               "intrusion_pages": []}
        # note: one page winning all 15 trips top1_dominance only
        # at >= 25% AND the baseline-free absolute pass; with a
        # baseline present but identical features, delta signals
        # stay quiet — use a spread baseline for the quiet case.
        q = {}
        wins = {}
        for i in range(1, 41):
            page = f"wiki/entities/p{i % 8}.md"
            q[f"Q{i:03d}"] = feats(top1=page)
            wins[page] = wins.get(page, 0) + 1
        agg = {"probes": 40, "median_result_count": 20,
               "top1_wins": wins, "intrusion_pages": []}
        base = self.baseline(q, wins)
        self.assertEqual(watch.detect_anomalies(q, agg, base), [])

    def test_poisoned_trips_named_signals(self):
        poison = "wiki/entities/poison.md"
        base_q, cur_q = {}, {}
        base_wins = {}
        for i in range(1, 41):
            page = f"wiki/entities/p{i % 8}.md"
            base_q[f"Q{i:03d}"] = feats(top1=page)
            base_wins[page] = base_wins.get(page, 0) + 1
            cur_q[f"Q{i:03d}"] = feats(
                top1=poison, share=0.6, conc=0.4,
                top10=[poison] + [page], new=[poison])
        agg = {"probes": 40, "median_result_count": 20,
               "top1_wins": {poison: 40}, "intrusion_pages": [poison]}
        base = self.baseline(base_q, base_wins)
        signals = {a["signal"] for a in
                   watch.detect_anomalies(cur_q, agg, base)}
        self.assertIn("top1_dominance", signals)
        self.assertIn("new_page_intrusion", signals)
        self.assertIn("top1_share_jump", signals)

    def test_concentration_absolute_signal_needs_no_baseline(self):
        q = {"Q001": feats(conc=0.9, top_collection="wiki/sources",
                           top10=["wiki/sources/a.md"] * 9
                           + ["wiki/entities/b.md"])}
        agg = {"probes": 1, "median_result_count": 20,
               "top1_wins": {}, "intrusion_pages": [],
               "collection_shares": {"wiki/sources": 0.10,
                                     "wiki/entities": 0.02}}
        signals = {a["signal"] for a in
                   watch.detect_anomalies(q, agg, None)}
        self.assertIn("concentration", signals)

    def test_giant_collection_at_base_rate_is_quiet(self):
        # raw/sources is ~64% of the real corpus: a top-10 that
        # is 90% raw/sources is base rate, not a flood — the
        # first real run (2030-10-20) fired 51 of 93 probes
        # before the signal was made base-rate aware.
        q = {"Q001": feats(conc=0.9, top_collection="raw/sources",
                           top10=["raw/sources/a.md"] * 9
                           + ["wiki/entities/b.md"])}
        agg = {"probes": 1, "median_result_count": 20,
               "top1_wins": {}, "intrusion_pages": [],
               "collection_shares": {"raw/sources": 0.64}}
        self.assertEqual(watch.detect_anomalies(q, agg, None), [])


class FixtureRunTests(unittest.TestCase):
    """End-to-end on a temp corpus with the real search engine."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir(parents=True)
        for name in ("wiki_search.py", "wiki_retrieval_watch.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        (self.tmp / "evaluation").mkdir()
        (self.tmp / "evaluation" / "extended-questions.jsonl").write_text("")
        (self.tmp / "evaluation" / "golden-questions.jsonl").write_text(
            json.dumps({"id": "GQ-001", "question":
                        "How many members are in the demo household?"}) + "\n"
            + json.dumps({"id": "GQ-002", "question":
                          "What is the galen seat decision?"}) + "\n")
        pages = {
            "wiki/entities/owner.md":
                "# Owner\n\nThe demo household has three members. "
                "Members household members household.\n",
            "wiki/sources/alpha.md":
                "# Alpha\n\nThe rights gate was reversed; the "
                "registry stands as a record only.\n",
            "wiki/concepts/beta.md":
                "# Beta\n\nHosting plan credit tier downgrade "
                "billing watch.\n",
            "raw/sources/gamma.md":
                "# Gamma\n\nThe galen seat decision: the owner "
                "ruling opened the seat.\n",
        }
        for rel, text in pages.items():
            p = self.tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_watch(self):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / "wiki_retrieval_watch.py")],
            capture_output=True, text=True, timeout=300)

    def test_baseline_then_poison_trips(self):
        first = self.run_watch()
        self.assertTrue(
            (self.tmp / "evaluation" / "retrieval-baseline.json")
            .is_file())
        poison = self.tmp / "wiki/entities/zz-poison.md"
        poison.write_text(
            "# Poison\n\n" + ("members household galen seat decision "
                               "owner ruling " * 40) + "\n")
        second = self.run_watch()
        self.assertEqual(second.returncode, 1, second.stdout)
        self.assertIn("zz-poison.md", second.stdout)
        self.assertIn("ANOMALIES", second.stdout)


if __name__ == "__main__":
    unittest.main()
