#!/usr/bin/env python3
"""Iterative retrieval passes (W3, 2026-10-22):
scripts/wiki_iterate.py + the stage-7 hook in
scripts/wiki_search.py hybrid_rank.

Pins:
  - the refinement's source: terms are drawn from the
    previous pass's GOVERNED output (its top hits' leads),
    scored draft_tf x idf, query terms and corpus-stopwords
    excluded — the corpus speaking its own vocabulary back;
  - the fusion: reciprocal rank (k=60) over the passes, a
    page's score the sum of its per-pass terms, its detail
    the earliest pass's plus an "iteration" block naming
    its rank in every pass and the first pass that
    surfaced it;
  - the bound: at most max_passes passes (default 2, hard
    cap 3), with the named stopping rules — empty first
    pass, no refinement terms, stable top-10 — and a
    single-pass outcome returns pass 1's list UNCHANGED
    (scores included, no fusion applied to one ranking);
  - governance composition (W1.5), strongest form: the
    refinement draft never reads a withheld page — a term
    that exists only in the withheld page's vocabulary
    (and a page sharing only that vocabulary) cannot be
    reached by iteration — while the ungoverned
    counterfactual draft DOES contain the term, proving
    where it would have come from; the withheld page
    itself is re-filtered at every pass and never
    surfaces;
  - the default path is untouched: same-process A/B —
    hybrid_rank without the argument vs iterate=None —
    identical (score, path, detail) rankings, and no
    "iteration" key leaks into default details;
  - determinism: two iterated runs produce identical
    rankings and identical iteration records.

Fixture corpora are in-memory (Path, text) pairs on fake
absolute paths — no disk, no tempfile.

Run:  python3 -m unittest scripts.tests.test_wiki_iterate
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


iterate = _load("wiki_iterate", ROOT / "scripts" / "wiki_iterate.py")
ws = _load("wiki_search_for_iterate_tests",
           ROOT / "scripts" / "wiki_search.py")


def doc(name, text):
    return (Path("/fix") / name, text)


def paths(ranked):
    return [str(p) for _s, p, _t, _d in ranked]


def by_path(ranked):
    return {str(p): (s, d) for s, p, _t, d in ranked}


# --- The signal corpus -------------------------------------
# The anchor is the strong lexical hit for "signal beacon";
# its lead speaks of the harbour entrance. The harbour
# record shares that lead vocabulary but NO query term and
# no link, so the default pipeline never recalls it; the
# refinement drawn from the anchor's lead is the only road
# in. Three unrelated fillers dilute document frequencies
# below the stopword share.
SIGNAL_DOCS = [
    doc("anchor.md",
        "# Signal beacon anchor\n"
        "signal beacon harbour entrance. signal beacon "
        "harbour entrance marks the pilot channel. harbour "
        "entrance signal."),
    doc("harbour.md",
        "# Harbour entrance record\n"
        "harbour entrance pilot channel. harbour entrance "
        "marks. pilot channel harbour."),
    doc("orchard.md",
        "# Orchard\n"
        "orchard ledger apples pears cider press harvest "
        "orchard ledger apples."),
    doc("quarry.md",
        "# Quarry\n"
        "quarry stone granite slab quarry ledger stone dust."),
    doc("meadow.md",
        "# Meadow\n"
        "meadow grass clover brook meadow grass clover."),
]
SIGNAL_QUERY = ["signal", "beacon"]


class FusionTests(unittest.TestCase):
    def test_rrf_arithmetic_and_attribution(self):
        d_a = {"bm25": 3.0}
        d_b = {"bm25": 2.0}
        d_c = {"bm25": 1.0}
        p1 = [(9.0, Path("/fix/a.md"), "ta", d_a),
              (8.0, Path("/fix/b.md"), "tb", d_b)]
        p2 = [(7.0, Path("/fix/b.md"), "tb", d_b),
              (6.0, Path("/fix/c.md"), "tc", d_c)]
        fused, ranks = iterate.fuse_passes([p1, p2])
        got = by_path(fused)
        # a: rank 1 in pass 1 only -> 1/61.
        self.assertAlmostEqual(got["/fix/a.md"][0], 1 / 61)
        # b: rank 2 then rank 1 -> 1/62 + 1/61, so b wins.
        self.assertAlmostEqual(got["/fix/b.md"][0], 1 / 62 + 1 / 61)
        self.assertEqual(paths(fused)[0], "/fix/b.md")
        self.assertEqual(ranks["/fix/b.md"], {1: 2, 2: 1})
        it_b = got["/fix/b.md"][1]["iteration"]
        self.assertEqual(it_b["pass_ranks"], {"1": 2, "2": 1})
        self.assertEqual(it_b["first_seen_pass"], 1)
        it_c = got["/fix/c.md"][1]["iteration"]
        self.assertEqual(it_c["first_seen_pass"], 2)
        # detail is the earliest pass's, not a later pass's.
        self.assertEqual(got["/fix/a.md"][1]["bm25"], 3.0)

    def test_clamp(self):
        self.assertEqual(iterate.clamp_max_passes(2), 2)
        self.assertEqual(iterate.clamp_max_passes(99),
                         iterate.HARD_MAX_PASSES)
        self.assertEqual(iterate.clamp_max_passes(0), 1)
        self.assertEqual(iterate.clamp_max_passes(None),
                         iterate.DEFAULT_MAX_PASSES)
        self.assertEqual(iterate.clamp_max_passes("x"),
                         iterate.DEFAULT_MAX_PASSES)


class RefinementTests(unittest.TestCase):
    def test_terms_come_from_the_given_list_only(self):
        # The builder reads ONLY the ranked list it is
        # handed: given the governed pass-1 output (the
        # anchor alone), the harbour record's own text
        # contributes nothing — the terms are the anchor
        # lead's, scored and filtered.
        ranked = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS)
        self.assertEqual(paths(ranked), ["/fix/anchor.md"])
        rec = iterate.build_refinement(ws, SIGNAL_QUERY,
                                       ranked, SIGNAL_DOCS)
        terms = {e["term"] for e in rec["terms"]}
        self.assertIn("harbour", terms)
        self.assertIn("entrance", terms)
        self.assertNotIn("signal", terms)     # query term
        self.assertNotIn("beacon", terms)     # query term
        self.assertNotIn("orchard", terms)    # never in a seed
        self.assertEqual(rec["draft"]["seed_paths"],
                         ["/fix/anchor.md"])
        for e in rec["terms"]:
            self.assertEqual(e["weight"], iterate.REFINE_WEIGHT)
            self.assertIn("draft_tf", e)
            self.assertIn("idf", e)

    def test_second_pass_surfaces_the_neighbour(self):
        off = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS)
        self.assertNotIn("/fix/harbour.md", paths(off))
        on = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                            iterate=True)
        got = by_path(on)
        self.assertIn("/fix/harbour.md", got)
        _s, d = got["/fix/harbour.md"]
        self.assertEqual(d["iteration"]["first_seen_pass"], 2)
        self.assertEqual(set(d["iteration"]["pass_ranks"]),
                         {"2"})
        self.assertEqual(paths(on)[0], "/fix/anchor.md")
        rec = ws.LAST_ITERATION["record"]
        self.assertTrue(ws.LAST_ITERATION["applied"])
        self.assertEqual(rec["kind"], "iterative-retrieval")
        self.assertEqual(rec["passes_run"], 2)
        self.assertEqual(rec["stop_reason"], "max-passes")
        self.assertTrue(rec["fused"])
        ref = rec["passes"][1]["refinement_from"]
        self.assertEqual(ref["seed_paths"], ["/fix/anchor.md"])
        self.assertIn("harbour",
                      {e["term"] for e in ref["terms"]})
        self.assertIn("/fix/harbour.md",
                      rec["passes"][1]["new_in_top10"])


class StoppingRuleTests(unittest.TestCase):
    def test_empty_first_pass_stops(self):
        ranked = ws.hybrid_rank(["zzznomatch"], SIGNAL_DOCS,
                                iterate=True)
        self.assertEqual(ranked, [])
        rec = ws.LAST_ITERATION["record"]
        self.assertEqual(rec["passes_run"], 1)
        self.assertEqual(rec["stop_reason"], "empty-first-pass")
        self.assertFalse(rec["fused"])

    def test_no_refinement_terms_returns_pass1_unchanged(self):
        docs = [
            doc("solo.md", "# Alpha beta\nalpha beta alpha beta."),
            doc("f1.md", "# F1\nmulch compost rows turnips."),
            doc("f2.md", "# F2\ngravel silt embankment survey."),
        ]
        off = ws.hybrid_rank(["alpha", "beta"], docs)
        on = ws.hybrid_rank(["alpha", "beta"], docs, iterate=True)
        rec = ws.LAST_ITERATION["record"]
        self.assertEqual(rec["stop_reason"], "no-refinement-terms")
        self.assertEqual(rec["passes_run"], 1)
        self.assertFalse(rec["fused"])
        # Unchanged means unchanged: scores, order, details.
        self.assertEqual([(s, str(p), d) for s, p, _t, d in off],
                         [(s, str(p), d) for s, p, _t, d in on])

    def test_max_passes_one_is_a_no_op_with_a_record(self):
        off = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS)
        on = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                            iterate={"max_passes": 1})
        rec = ws.LAST_ITERATION["record"]
        self.assertEqual(rec["passes_run"], 1)
        self.assertEqual(rec["stop_reason"], "max-passes")
        self.assertFalse(rec["fused"])
        self.assertEqual([(s, str(p)) for s, p, _t, _d in off],
                         [(s, str(p)) for s, p, _t, _d in on])

    def test_stable_top10_stops_the_third_pass(self):
        ranked = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                                iterate={"max_passes": 3})
        rec = ws.LAST_ITERATION["record"]
        self.assertEqual(rec["stop_reason"], "stable-top10")
        self.assertEqual(rec["passes_run"], 3)
        self.assertIn("/fix/harbour.md", paths(ranked))


class DefaultIdentityTests(unittest.TestCase):
    def test_default_ab_identical_and_no_leak(self):
        a = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS)
        b = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                           iterate=None)
        self.assertEqual([(s, str(p), d) for s, p, _t, d in a],
                         [(s, str(p), d) for s, p, _t, d in b])
        for _s, _p, _t, d in a:
            self.assertNotIn("iteration", d)
        self.assertFalse(ws.LAST_ITERATION["applied"])
        self.assertIsNone(ws.LAST_ITERATION["record"])

    def test_determinism(self):
        r1 = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                            iterate=True)
        rec1 = ws.LAST_ITERATION["record"]
        r2 = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                            iterate=True)
        rec2 = ws.LAST_ITERATION["record"]
        self.assertEqual([(s, str(p)) for s, p, _t, _d in r1],
                         [(s, str(p)) for s, p, _t, _d in r2])
        self.assertEqual(rec1, rec2)


class CompositionTests(unittest.TestCase):
    def test_caller_expansion_terms_ride_every_pass(self):
        exp = {"kind": "fixture-expansion",
               "expansion_terms": [{"term": "harbour",
                                    "weight": 0.5}]}
        ranked = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                                expansion=exp, iterate=True)
        rec = ws.LAST_ITERATION["record"]
        self.assertIn("/fix/harbour.md", paths(ranked))
        p1_terms = {e["term"] for e in
                    rec["passes"][0]["stage0_terms"]}
        p2_terms = {e["term"] for e in
                    rec["passes"][1]["stage0_terms"]}
        self.assertIn("harbour", p1_terms)
        self.assertIn("harbour", p2_terms)

    def test_onehop_and_iterate_compose(self):
        ranked = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS,
                                onehop=True, iterate=True)
        self.assertTrue(ws.LAST_ITERATION["applied"])
        self.assertIsNotNone(ws.LAST_ITERATION["record"])
        self.assertIn("/fix/anchor.md", paths(ranked))

    def test_injecting_wrapper_does_not_recurse(self):
        # Regression: the battery gate wraps hybrid_rank and
        # injects iterate=True. The seam re-enters
        # hybrid_rank by its module-global name for pass 2,
        # so an unguarded wrapper re-injects on every pass
        # and recurses without bound (the first gate-check
        # run died with RecursionError in the ON arm). The
        # guarded wrapper injects at the outermost call only:
        # one iteration, whose passes run the plain pipeline.
        orig = ws.hybrid_rank
        ws.hybrid_rank = iterate.make_injecting_wrapper(
            orig, iterate=True)
        try:
            ranked = ws.hybrid_rank(SIGNAL_QUERY, SIGNAL_DOCS)
        finally:
            ws.hybrid_rank = orig
        self.assertIn("/fix/harbour.md", paths(ranked))
        rec = ws.LAST_ITERATION["record"]
        self.assertEqual(rec["passes_run"], 2)
        self.assertTrue(rec["fused"])


# --- The governance corpus ---------------------------------
# The dead claim is the strongest lexical hit for the query
# and the ONLY carrier of the signature terms zanzibar /
# quixotic; the relic shares that signature vocabulary and
# nothing else, so the signature is the only road to it.
# The successor hits the query too, more weakly.
GOV_DOCS = [
    doc("dead.md",
        "# Dead claim\n"
        "dead claim zanzibar quixotic. dead claim zanzibar. "
        "The dead claim named zanzibar quixotic terms."),
    doc("successor.md",
        "# Current ruling\n"
        "The current ruling replaced the dead claim. "
        "current ruling harbour signal registry."),
    doc("relic.md",
        "# Relic note\n"
        "zanzibar quixotic relic. zanzibar quixotic."),
    doc("orchard.md",
        "# Orchard\n"
        "orchard ledger apples pears cider press harvest."),
    doc("quarry.md",
        "# Quarry\n"
        "quarry stone granite slab quarry ledger stone dust."),
]
GOV_QUERY = ["dead", "claim"]
GOV = {"pages": {"/fix/dead.md": {
    "state": "withheld",
    "reasons": ["superseded by [[successor]] (status)"]}},
    "state_hash": "fixture"}


class GovernanceCompositionTests(unittest.TestCase):
    def test_withheld_vocabulary_never_enters_the_draft(self):
        ranked = ws.hybrid_rank(GOV_QUERY, GOV_DOCS,
                                governance=GOV, iterate=True)
        got = paths(ranked)
        # The withheld page never surfaces — at any pass.
        self.assertNotIn("/fix/dead.md", got)
        withheld = {w["path"]
                    for w in ws.LAST_GOVERNANCE["withheld"]}
        self.assertIn("/fix/dead.md", withheld)
        # The relic, reachable ONLY through the withheld
        # page's signature vocabulary, never surfaces.
        self.assertNotIn("/fix/relic.md", got)
        rec = ws.LAST_ITERATION["record"]
        for prec in rec["passes"]:
            self.assertNotIn("/fix/dead.md", prec["top10"])
            ref = prec.get("refinement_from")
            if ref:
                self.assertNotIn("/fix/dead.md",
                                 ref["seed_paths"])
                terms = {e["term"] for e in ref["terms"]}
                self.assertNotIn("zanzibar", terms)
                self.assertNotIn("quixotic", terms)

    def test_ungoverned_counterfactual_draft_has_the_term(self):
        # Without governance the dead claim IS pass 1's top
        # hit, and a draft from that list speaks its
        # signature — proving the governed draft's silence
        # comes from the draft's source, not from the terms
        # being un-draftable.
        ranked = ws.hybrid_rank(GOV_QUERY, GOV_DOCS,
                                governance=False)
        self.assertEqual(paths(ranked)[0], "/fix/dead.md")
        rec = iterate.build_refinement(ws, GOV_QUERY, ranked,
                                       GOV_DOCS)
        terms = {e["term"] for e in rec["terms"]}
        self.assertIn("zanzibar", terms)
        self.assertIn("/fix/dead.md", rec["draft"]["seed_paths"])

    def test_severance_composition(self):
        sev = {"entries": [{"kind": "page",
                            "page": "/fix/successor.md",
                            "id": "sev-fixture"}]}
        ranked = ws.hybrid_rank(GOV_QUERY, GOV_DOCS,
                                severance=sev, iterate=True)
        self.assertNotIn("/fix/successor.md", paths(ranked))
        for prec in ws.LAST_ITERATION["record"]["passes"]:
            self.assertNotIn("/fix/successor.md", prec["top10"])


if __name__ == "__main__":
    unittest.main()
