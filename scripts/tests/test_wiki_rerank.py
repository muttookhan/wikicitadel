#!/usr/bin/env python3
"""The reranker seam (W1.1, 2026-10-22): scripts/wiki_rerank.py
behind hybrid_rank's stage 4.

Pins, on fixture corpora in temp dirs (never the live corpus):

  - the DEFAULT seam reproduces the pre-seam pipeline: hybrid_rank
    with no reranker argument and hybrid_rank with an explicit
    coverage reranker return identical (score, path) sequences,
    and a pool candidate's detail["rerank"] is the legacy
    multiplier 1 + 0.25 * coverage + 0.15 * title_frac;
  - the seam SWAPS: a stub reranker injected into hybrid_rank
    replaces the default — its multiplier lands on the detail,
    its name is stamped, and ordering follows the stub;
  - every detail carries the calibrated relevance + cut-off
    standing (rerank_relevance / below_cutoff), and an explicit
    relevance_cutoff moves the flag without moving any score;
  - cut-off CALIBRATION: calibrate_cutoff recovers a known
    threshold on synthetic samples under both objectives, with
    the abstention-leaning tie-break (fewer false positives);
  - the LISTWISE stage is GATED: a reversing listwise scorer
    changes nothing while the gate is closed (the default), and
    permutes — stamping listwise_from — only when opened;
    scores travel with their documents;
  - cross-encoder long-passage handling: chunk_windows covers a
    long passage in overlapping windows and the passage score is
    the MAX window score (a late-window match wins);
  - ColBERT-style MaxSim: a document sharing the query's tokens
    out-relevances one sharing none, through the bounded lift;
  - the registry rejects unknown kinds, and a model-backed
    cross-encoder with no scorer and no FlagEmbedding raises
    RerankerUnavailable instead of silently substituting;
  - the ranx-style comparison runs end-to-end on a fixture and
    reports per-model metrics with zero swallowed errors.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("wiki_search_rerank", ROOT / "scripts" / "wiki_search.py")
rr = _load("wiki_rerank", ROOT / "scripts" / "wiki_rerank.py")
bench = _load("wiki_benchmark_rerank", ROOT / "scripts" / "wiki_benchmark.py")


def _docs(root):
    """A tiny corpus: one page whose lead + title cover the query
    'zebra quokka', one whose body repeats 'zebra' but never
    covers 'quokka', and fillers."""
    docs = [
        (root / "wiki" / "zebra-quokka.md",
         "---\ntitle: Zebra Quokka\n---\n# Zebra Quokka\n\n"
         "The zebra and the quokka are both covered here, plainly, "
         "in the lead.\n"),
        (root / "wiki" / "zebra-only.md",
         "---\ntitle: Zebra Only\n---\n# Zebra Only\n\n"
         + "zebra " * 30 + "\n"),
    ]
    for i in range(6):
        docs.append((root / "wiki" / f"filler-{i}.md",
                     f"---\ntitle: Filler {i}\n---\n# Filler {i}\n\n"
                     "Unrelated notes about gardening and weather.\n"))
    return docs


class FixtureBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        self.docs = _docs(self.root)
        self.adj = ws.build_link_graph(self.docs)
        self.terms = ws.tokenize("zebra quokka")

    def tearDown(self):
        self._tmp.cleanup()


class TestDefaultSeamIdentity(FixtureBase):
    def test_default_matches_explicit_coverage(self):
        a = ws.hybrid_rank(self.terms, self.docs, self.adj,
                           severance=False)
        b = ws.hybrid_rank(self.terms, self.docs, self.adj,
                           severance=False,
                           reranker=rr.get_reranker(
                               "coverage",
                               coverage_w=ws.RERANK_COVERAGE_W,
                               title_w=ws.RERANK_TITLE_W,
                               max_lift=ws.RERANK_COVERAGE_W
                               + ws.RERANK_TITLE_W,
                               tokenize=ws.tokenize))
        self.assertEqual([(s, str(p)) for s, p, _t, _d in a],
                         [(s, str(p)) for s, p, _t, _d in b])

    def test_legacy_multiplier_on_detail(self):
        ranked = ws.hybrid_rank(self.terms, self.docs, self.adj,
                                severance=False)
        top = ranked[0]
        self.assertEqual(top[1].name, "zebra-quokka.md")
        # Full lead + title coverage of a 2-term query:
        # cov = 1, title_frac = 1 -> 1 + 0.25 + 0.15 = 1.40.
        self.assertAlmostEqual(top[3]["rerank"], 1.40, places=4)
        self.assertEqual(top[3]["reranker"], "coverage")
        self.assertAlmostEqual(top[3]["rerank_relevance"], 1.0,
                               places=4)
        self.assertFalse(top[3]["below_cutoff"])


class _StubReranker(rr.Reranker):
    """Relevance 1.0 for the candidate whose title contains the
    chosen phrase, 0.0 for every other candidate."""
    name = "stub"

    def __init__(self, title_phrase):
        self.title_phrase = title_phrase

    def rerank(self, query_terms, candidates):
        out = {}
        for cand in candidates:
            rel = 1.0 if self.title_phrase in \
                cand["title"].lower() else 0.0
            out[cand["key"]] = rr.RerankSignal(
                multiplier=1.0 + 0.40 * rel, relevance=rel,
                signals={"stub": True})
        return out


class TestSeamSwap(FixtureBase):
    def test_stub_replaces_default(self):
        stub = _StubReranker("zebra only")
        ranked = ws.hybrid_rank(self.terms, self.docs, self.adj,
                                severance=False, reranker=stub)
        for _s, _p, _t, d in ranked:
            self.assertEqual(d["reranker"], "stub")
        by_name = {p.name: d for _s, p, _t, d in ranked}
        self.assertAlmostEqual(by_name["zebra-only.md"]["rerank"],
                               1.40, places=4)
        self.assertAlmostEqual(
            by_name["zebra-only.md"]["rerank_relevance"], 1.0,
            places=4)
        # The fully-covering page loses its legacy lift under the
        # stub: its multiplier is the neutral 1.0.
        self.assertAlmostEqual(by_name["zebra-quokka.md"]["rerank"],
                               1.0, places=4)

    def test_cutoff_flag_moves_without_moving_scores(self):
        a = ws.hybrid_rank(self.terms, self.docs, self.adj,
                           severance=False)
        b = ws.hybrid_rank(self.terms, self.docs, self.adj,
                           severance=False, relevance_cutoff=1.01)
        self.assertEqual([s for s, _p, _t, _d in a],
                         [s for s, _p, _t, _d in b])
        self.assertTrue(all(d["below_cutoff"]
                            for _s, _p, _t, d in b))


class TestCalibration(unittest.TestCase):
    def test_recovers_threshold_f1(self):
        samples = [(0.9, True), (0.8, True), (0.7, True),
                   (0.2, False), (0.1, False), (0.05, False)]
        fit = rr.calibrate_cutoff(samples, objective="f1")
        self.assertEqual(fit["cutoff"], 0.7)
        self.assertEqual(fit["value"], 1.0)
        self.assertEqual(fit["confusion"],
                         {"tp": 3, "fp": 0, "tn": 3, "fn": 0})

    def test_recovers_threshold_agreement(self):
        samples = [(0.95, True), (0.6, True), (0.4, False),
                   (0.3, False)]
        fit = rr.calibrate_cutoff(samples, objective="agreement")
        self.assertEqual(fit["cutoff"], 0.6)
        self.assertEqual(fit["value"], 1.0)

    def test_tie_break_prefers_fewer_false_positives(self):
        # t=0.95 (tp=1, fp=0, fn=1) and t=0.5 (tp=2, fp=2, fn=0)
        # tie at F1 2/3; the fit must pick the threshold with
        # fewer false positives (the abstention-expensive
        # direction): t=0.95.
        samples = [(0.95, True), (0.5, True), (0.7, False),
                   (0.6, False), (0.1, False)]
        fit = rr.calibrate_cutoff(samples, objective="f1")
        self.assertAlmostEqual(fit["value"], 2 / 3, places=4)
        self.assertEqual(fit["cutoff"], 0.95)
        self.assertEqual(fit["confusion"]["fp"], 0)

    def test_cutoff_below(self):
        c = rr.RelevanceCutoff(0.5)
        self.assertTrue(c.below(0.49))
        self.assertFalse(c.below(0.5))
        self.assertFalse(c.below(0.9))
        self.assertEqual(c.to_dict(), {"relevance_cutoff": 0.5})


class _ReverseListwise:
    name = "reverse-stub"

    def __init__(self):
        self.inner = rr.ListwiseReranker(
            scorer=lambda q, window: list(reversed(window)),
            window=25, stride=25)

    def rerank_order(self, query_terms, ordered):
        return self.inner.rerank_order(query_terms, ordered)


class TestListwiseGate(FixtureBase):
    def test_gate_closed_by_default(self):
        plain = ws.hybrid_rank(self.terms, self.docs, self.adj,
                               severance=False)
        gated = ws.hybrid_rank(self.terms, self.docs, self.adj,
                               severance=False,
                               listwise=_ReverseListwise())
        self.assertEqual([str(p) for _s, p, _t, _d in plain],
                         [str(p) for _s, p, _t, _d in gated])
        self.assertFalse(any("listwise_from" in d
                             for _s, _p, _t, d in gated))
        self.assertFalse(rr.listwise_enabled(False, env={}))

    def test_gate_open_permutates_and_stamps(self):
        plain = ws.hybrid_rank(self.terms, self.docs, self.adj,
                               severance=False)
        opened = ws.hybrid_rank(self.terms, self.docs, self.adj,
                                severance=False,
                                listwise=_ReverseListwise(),
                                enable_listwise=True)
        self.assertEqual([str(p) for _s, p, _t, _d in opened],
                         [str(p) for _s, p, _t, _d in
                          reversed(plain)])
        # Scores travel with their documents.
        self.assertEqual([s for s, _p, _t, _d in opened],
                         [s for s, _p, _t, _d in reversed(plain)])
        self.assertTrue(any("listwise_from" in d
                            for _s, _p, _t, d in opened))

    def test_env_opens_gate(self):
        self.assertTrue(rr.listwise_enabled(
            False, env={rr.LISTWISE_ENV_VAR: "1"}))
        self.assertFalse(rr.listwise_enabled(
            False, env={rr.LISTWISE_ENV_VAR: "0"}))

    def test_no_scorer_raises_unavailable(self):
        lw = rr.ListwiseReranker()
        with self.assertRaises(rr.RerankerUnavailable):
            lw.rerank_order(["zebra"], [{"key": "a"}])


class TestCrossEncoder(unittest.TestCase):
    def test_chunk_windows_cover_long_passage(self):
        wins = rr.CrossEncoderReranker.chunk_windows(1200, 512, 256)
        self.assertEqual(wins[0], (0, 512))
        self.assertEqual(wins[-1][1], 1200)
        for (s0, _e0), (s1, _e1) in zip(wins, wins[1:]):
            self.assertEqual(s1 - s0, 256)  # overlap by stride
        self.assertEqual(
            rr.CrossEncoderReranker.chunk_windows(100, 512, 256),
            [(0, 100)])
        self.assertEqual(
            rr.CrossEncoderReranker.chunk_windows(0, 512, 256), [])

    def test_max_window_speaks_for_passage(self):
        # The matching chunk is the LAST window; max aggregation
        # must surface it (a head-truncating scorer would miss).
        def scorer(query, passage):
            return 4.0 if "quokka" in passage else -4.0

        r = rr.CrossEncoderReranker(scorer=scorer, window_tokens=8,
                                    stride_tokens=4,
                                    tokenize=rr.fallback_tokenize)
        text = " ".join(["filler"] * 20 + ["quokka"])
        cand = {"key": 1, "title": "T", "text": text,
                "coverage": 0.0, "title_frac": 0.0}
        sig = r.rerank(["quokka"], [cand])[1]
        self.assertAlmostEqual(sig.signals["pair_logit_max"], 4.0)
        self.assertGreater(sig.relevance, 0.98)
        self.assertAlmostEqual(sig.multiplier,
                               1.0 + 0.40 * sig.relevance)

    def test_lexical_reference_scorer_runs(self):
        r = rr.get_reranker(
            "cross-encoder",
            scorer=rr.LexicalPairScorer(tokenize=rr.fallback_tokenize),
            tokenize=rr.fallback_tokenize)
        cand = {"key": 7, "title": "Zebra", "coverage": 0.0,
                "title_frac": 0.0,
                "text": "the zebra and the quokka together"}
        sig = r.rerank(["zebra", "quokka"], [cand])[7]
        self.assertGreater(sig.relevance, 0.9)

    def test_model_backed_without_dependency_raises(self):
        try:
            import FlagEmbedding  # noqa: F401
            self.skipTest("FlagEmbedding is installed here")
        except ImportError:
            pass
        r = rr.CrossEncoderReranker(tokenize=rr.fallback_tokenize)
        cand = {"key": 1, "title": "T", "text": "some passage text",
                "coverage": 0.0, "title_frac": 0.0}
        with self.assertRaises(rr.RerankerUnavailable):
            r.rerank(["some"], [cand])


class TestLateInteraction(unittest.TestCase):
    def test_maxsim_orders_by_token_overlap(self):
        r = rr.get_reranker("colbert", tokenize=rr.fallback_tokenize)
        cands = [
            {"key": 1, "title": "Zebra Quokka", "coverage": 0.0,
             "title_frac": 0.0,
             "text": "the zebra and the quokka in the lead"},
            {"key": 2, "title": "Gardening", "coverage": 0.0,
             "title_frac": 0.0,
             "text": "gardening weather soil rain sunshine"},
        ]
        out = r.rerank(["zebra", "quokka"], cands)
        self.assertGreater(out[1].relevance, out[2].relevance)
        for sig in out.values():
            self.assertGreaterEqual(sig.relevance, 0.0)
            self.assertLessEqual(sig.relevance, 1.0)
            self.assertGreaterEqual(sig.multiplier, 1.0)
            self.assertLessEqual(sig.multiplier, 1.40)


class TestRegistry(unittest.TestCase):
    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            rr.get_reranker("splade")

    def test_kinds_listed(self):
        self.assertEqual(rr.RERANKER_KINDS,
                         ("coverage", "cross-encoder", "colbert"))


class TestCompareSmoke(FixtureBase):
    def test_compare_reports_models_and_no_swallowed_errors(self):
        # The fixture corpus lives in a temp dir, so ranked paths
        # surface as absolute paths (the relative_to(ROOT) form
        # only appears on the live corpus); cite that exact form.
        questions = [{
            "id": "FQ-1", "question": "zebra quokka",
            "must_cite": [str(self.docs[0][0])],
            "acceptable_cites": [],
        }]
        built = rr.build_compare_rerankers(
            ws, ["coverage", "colbert"])
        report = rr.compare_rerankers(ws, bench, self.docs,
                                      self.adj, questions, built)
        for name in ("coverage", "colbert"):
            m = report["models"][name]
            self.assertEqual(m["questions_scored"], 1)
            self.assertEqual(m["invocation_errors"], [])
            self.assertEqual(m["citation_coverage"]["@1"], 1.0)
        self.assertIn("colbert", report["deltas_vs_default"])


if __name__ == "__main__":
    unittest.main()
