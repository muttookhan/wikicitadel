#!/usr/bin/env python3
"""Usage-weighted link strength (W1.12, 2026-10-22):
scripts/wiki_usage_weights.py behind the wiki_rerank seam.

Pins:
  - the decay math: a deposit halves every HALF_LIFE_DAYS;
  - the daily deposit cap (one day can never contribute more
    than DAILY_DEPOSIT_CAP, however many events land on it);
  - the guardrail bound: under ANY event history the usage lift
    stays below LIFT_SUPREMUM < MAX_USAGE_LIFT — a simulated
    10-year feedback loop (deposit at the cap daily) converges
    under the bound instead of running away, and once deposits
    stop the stock evaporates by exactly 2^(−days/HALF_LIFE);
  - the multiplier ratio between the most-used page and a
    never-used one never exceeds 1 + LIFT_SUPREMUM;
  - the relevance gate: below the seam's calibrated cut-off the
    applied lift is exactly 0; at/above it, the full lift;
  - the base relevance passes through unchanged (the calibrated
    scale is the base reranker's own) and usage is recorded in
    the signal's signals;
  - the loaders: use-log traversals deposit on sources (and on
    the filed-page → source edge), research searches deposit on
    the served page, undated events are counted but NEVER
    deposited, unmatched pages are counted when a corpus is
    given;
  - reproducibility: two builds from the same events + as-of
    produce identical artefacts;
  - the seam on a fixture corpus: with empty weights the ranked
    (score, path) sequence equals the default pipeline's
    exactly; with usage on the tied runner-up it overtakes —
    and only through the multiplier;
  - edge strength: 1.0 structural + the same bounded lift.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


uw = _load("wiki_usage_weights", ROOT / "scripts" / "wiki_usage_weights.py")
rr = _load("wiki_rerank_for_usage_tests", ROOT / "scripts" / "wiki_rerank.py")
ws = _load("wiki_search_for_usage_tests", ROOT / "scripts" / "wiki_search.py")

AS_OF = date(2026, 10, 22)


def ev(when, page, amount=1.0, edge_from=None, source="test"):
    return uw.Event(when, page, amount, source, edge_from=edge_from)


class DecayAndCapTests(unittest.TestCase):
    def test_decay_halves_each_half_life(self):
        self.assertEqual(uw.decay(0), 1.0)
        self.assertAlmostEqual(uw.decay(uw.HALF_LIFE_DAYS), 0.5)
        self.assertAlmostEqual(uw.decay(2 * uw.HALF_LIFE_DAYS), 0.25)
        self.assertEqual(uw.decay(-5), 1.0)  # future clamps, never > 1

    def test_single_deposit_ages(self):
        w = uw.UsageWeights([ev(AS_OF, "p", 2.0)], AS_OF)
        self.assertAlmostEqual(w.raw_of("p"), 2.0)
        w = uw.UsageWeights([ev(AS_OF - timedelta(days=30), "p", 2.0)],
                            AS_OF)
        self.assertAlmostEqual(w.raw_of("p"), 1.0)

    def test_daily_cap(self):
        # 50 events on one day count as DAILY_DEPOSIT_CAP, not 50.
        w = uw.UsageWeights([ev(AS_OF, "p", 1.0) for _ in range(50)],
                            AS_OF)
        self.assertAlmostEqual(w.raw_of("p"), uw.DAILY_DEPOSIT_CAP)

    def test_undated_events_never_deposited(self):
        w = uw.UsageWeights([ev(None, "p", 5.0)], AS_OF)
        self.assertEqual(w.raw_of("p"), 0.0)
        self.assertEqual(w.survey_counts["events_undated"], 1)
        self.assertFalse(w.active)


class GuardrailTests(unittest.TestCase):
    def test_lift_supremum_below_max(self):
        self.assertLess(uw.LIFT_SUPREMUM, uw.MAX_USAGE_LIFT)
        # even an absurd raw cannot reach MAX (saturation), and a
        # capped-history raw cannot reach RAW_SUPREMUM's lift.
        self.assertLess(uw.lift_from_raw(1e12), uw.MAX_USAGE_LIFT)
        self.assertAlmostEqual(uw.lift_from_raw(uw.RAW_SUPREMUM),
                               uw.LIFT_SUPREMUM, places=9)

    def test_feedback_loop_converges_under_bound(self):
        # The loop: a page served at the daily cap every day.
        # After any number of days, raw must stay under
        # RAW_SUPREMUM and converge to it from below — the stock
        # the loop can accumulate is bounded, so the loop's gain
        # is a contraction, never a runaway.
        for horizon in (30, 365, 3650):
            events = [ev(AS_OF - timedelta(days=back), "p",
                         uw.DAILY_DEPOSIT_CAP)
                      for back in range(horizon)]
            w = uw.UsageWeights(events, AS_OF)
            self.assertLessEqual(w.raw_of("p"),
                                 uw.RAW_SUPREMUM + 1e-9)
            self.assertLess(w.page_lift("p"), uw.MAX_USAGE_LIFT)
        # converged: within 1% of the supremum after 10 years
        self.assertGreater(w.raw_of("p"), 0.99 * uw.RAW_SUPREMUM)

    def test_evaporation_after_deposits_stop(self):
        events = [ev(AS_OF - timedelta(days=back), "p",
                      uw.DAILY_DEPOSIT_CAP) for back in range(365)]
        w_stop = uw.UsageWeights(events, AS_OF)
        w_later = uw.UsageWeights(events, AS_OF + timedelta(days=300))
        # 300 quiet days = 10 half-lives: raw shrinks by 2^10.
        self.assertAlmostEqual(w_later.raw_of("p"),
                               w_stop.raw_of("p") / 1024.0, places=6)

    def test_multiplier_ratio_bounded(self):
        # Most-used page in the world vs a never-used one: the
        # rerank multiplier ratio can never exceed 1 + LIFT_SUP.
        events = [ev(AS_OF - timedelta(days=back), "hot",
                     uw.DAILY_DEPOSIT_CAP) for back in range(3650)]
        w = uw.UsageWeights(events, AS_OF)
        docs = [(ROOT / "wiki" / "hot.md", ""),
                (ROOT / "wiki" / "cold.md", "")]
        stub = _StubBase(multiplier=1.2, relevance=0.9)
        r = uw.UsageWeightedReranker(stub, w, docs=docs)
        sigs = r.rerank(["q"], [{"key": 0}, {"key": 1}])
        ratio = sigs[0].multiplier / sigs[1].multiplier
        self.assertLessEqual(ratio, 1.0 + uw.LIFT_SUPREMUM + 1e-9)
        self.assertAlmostEqual(sigs[1].multiplier, 1.2)  # cold: untouched


class _StubBase:
    """A base reranker with fixed signals, for gate/ratio tests."""
    name = "stub"

    def __init__(self, multiplier=1.2, relevance=0.9):
        self.multiplier = multiplier
        self.relevance = relevance

    def rerank(self, query_terms, candidates):
        return {c["key"]: rr.RerankSignal(self.multiplier, self.relevance,
                                          {"coverage": 0.5})
                for c in candidates}


class GateAndSignalTests(unittest.TestCase):
    def _weights(self):
        return uw.UsageWeights(
            [ev(AS_OF - timedelta(days=d), "p", uw.DAILY_DEPOSIT_CAP)
             for d in range(60)], AS_OF)

    def test_below_cutoff_gets_zero_lift(self):
        w = self._weights()
        self.assertGreater(w.page_lift("p"), 0.0)
        r = uw.UsageWeightedReranker(
            _StubBase(relevance=0.30), w,
            docs=[(ROOT / "wiki" / "p.md", "")])
        # the gate is the seam's calibrated cut-off by default
        self.assertEqual(r.relevance_gate, rr.DEFAULT_RELEVANCE_CUTOFF)
        sig = r.rerank(["q"], [{"key": 0}])[0]
        self.assertEqual(sig.signals["usage_gate"], "below-cutoff")
        self.assertEqual(sig.signals["usage_lift"], 0.0)
        self.assertEqual(sig.multiplier, 1.2)  # exactly the base's

    def test_above_cutoff_full_lift_relevance_unchanged(self):
        w = self._weights()
        r = uw.UsageWeightedReranker(
            _StubBase(multiplier=1.2, relevance=0.9), w,
            docs=[(ROOT / "wiki" / "p.md", "")])
        sig = r.rerank(["q"], [{"key": 0}])[0]
        self.assertEqual(sig.signals["usage_gate"], "applied")
        self.assertAlmostEqual(sig.multiplier,
                               1.2 * (1.0 + w.page_lift("p")))
        self.assertEqual(sig.relevance, 0.9)  # the calibrated scale: untouched
        self.assertEqual(sig.signals["coverage"], 0.5)  # base signals kept

    def test_no_usage_is_exactly_neutral(self):
        w = uw.UsageWeights([], AS_OF)
        r = uw.UsageWeightedReranker(
            _StubBase(), w, docs=[(ROOT / "wiki" / "p.md", "")])
        sig = r.rerank(["q"], [{"key": 0}])[0]
        self.assertEqual(sig.multiplier, 1.2)  # float-exact
        self.assertEqual(sig.signals["usage_gate"], "no-usage")


class LoaderTests(unittest.TestCase):
    def test_use_event_deposits_and_edge(self):
        obj = {"kind": "use-event", "date": "2026-10-20",
               "page": "syntheses/answer", "use_kind": "synthesis",
               "sources": ["sources/paper-a", "wiki/sources/paper-b.md"],
               "supports": ["entities/x"], "contradicts": []}
        evs = uw.events_from_record(obj, "use-log")
        pages = {e.page: e.amount for e in evs}
        self.assertEqual(pages, {"sources/paper-a": 1.0,
                                 "sources/paper-b": 1.0,
                                 "entities/x": 1.0})
        self.assertTrue(all(e.edge_from == "syntheses/answer"
                            for e in evs))
        w = uw.UsageWeights(evs, AS_OF)
        self.assertGreater(w.raw_of("sources/paper-a"), 0.0)
        self.assertGreater(
            w.edge_strength("syntheses/answer", "sources/paper-a"), 1.0)
        self.assertEqual(
            w.edge_strength("syntheses/answer", "entities/none"), 1.0)

    def test_research_search_deposit(self):
        obj = {"kind": "search", "date": "2026-10-20",
               "page": "raw/sources/wave10-gap-closure.md (§2)",
               "query": "Bates 1989"}
        evs = uw.events_from_record(obj, "research-log")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].page, "raw/sources/wave10-gap-closure")
        self.assertEqual(evs[0].amount, uw.RESEARCH_DEPOSIT)

    def test_ask_trace_undated_counted_not_deposited(self):
        obj = {"kind": "ask-trace",
               "packing": {"packed": [{"page": "syntheses/a"}]},
               "retrieved_ids": ["syntheses/a", "syntheses/b"]}
        evs = uw.events_from_record(obj, "ask-traces")
        self.assertEqual(len(evs), 2)  # packed 1.0 + retrieved-only 0.25
        w = uw.UsageWeights(evs, AS_OF)
        self.assertEqual(w.raw_of("syntheses/a"), 0.0)  # undated: no deposit
        self.assertEqual(w.survey_counts["events_undated"], 2)

    def test_unmatched_counted_with_corpus(self):
        evs = [ev(AS_OF, "syntheses/real"), ev(AS_OF, "raw/sources/x")]
        w = uw.UsageWeights(evs, AS_OF, corpus_keys={"syntheses/real"})
        self.assertEqual(w.survey_counts["deposits_matched"], 1)
        self.assertEqual(w.survey_counts["deposits_unmatched"], 1)

    def test_rebuild_reproducible(self):
        evs = [ev(AS_OF - timedelta(days=d), "p", 1.0) for d in range(10)]
        evs.append(ev(AS_OF, "q", 1.0, edge_from="p"))
        a = uw.UsageWeights(evs, AS_OF).to_dict()
        b = uw.UsageWeights(list(evs), AS_OF).to_dict()
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))


class SeamIntegrationTests(unittest.TestCase):
    """hybrid_rank on a fixture corpus (paths need not exist —
    the ranker reads the (path, text) tuples it is given)."""

    TEXT = ("# {title}\n\nusage weights usage weights usage "
            "weights. The usage weights page explains usage "
            "weights in full.\n")

    def _docs(self):
        return [
            (ROOT / "wiki" / "alpha-notes.md",
             self.TEXT.format(title="Alpha Notes")),
            (ROOT / "wiki" / "beta-notes.md",
             self.TEXT.format(title="Beta Notes")),
        ]

    def test_empty_weights_identical_to_default(self):
        docs = self._docs()
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize("usage weights")
        default = ws.hybrid_rank(terms, docs, adj, severance=False)
        w = uw.UsageWeights([], AS_OF)
        reranker = uw.build_usage_reranker(ws, w, docs)
        boosted = ws.hybrid_rank(terms, docs, adj, severance=False,
                                 reranker=reranker)
        self.assertEqual([(s, str(p)) for s, p, _t, _d in default],
                         [(s, str(p)) for s, p, _t, _d in boosted])

    def test_usage_breaks_a_tie_upward_only(self):
        docs = self._docs()
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize("usage weights")
        default = ws.hybrid_rank(terms, docs, adj, severance=False)
        # identical texts: the tie breaks by path — alpha first.
        self.assertEqual(default[0][1].name, "alpha-notes.md")
        self.assertAlmostEqual(default[0][0], default[1][0])
        events = [ev(AS_OF - timedelta(days=d), "beta-notes",
                     uw.DAILY_DEPOSIT_CAP) for d in range(60)]
        w = uw.UsageWeights(events, AS_OF)
        reranker = uw.build_usage_reranker(ws, w, docs)
        boosted = ws.hybrid_rank(terms, docs, adj, severance=False,
                                 reranker=reranker)
        self.assertEqual(boosted[0][1].name, "beta-notes.md")
        self.assertGreater(boosted[0][0], default[0][0])
        # alpha's score is untouched (it carries no usage)
        alpha_u = [r for r in boosted if r[1].name == "alpha-notes.md"][0]
        alpha_d = [r for r in default if r[1].name == "alpha-notes.md"][0]
        self.assertEqual(alpha_u[0], alpha_d[0])
        self.assertEqual(alpha_u[3]["reranker"], "coverage+usage")


if __name__ == "__main__":
    unittest.main()
