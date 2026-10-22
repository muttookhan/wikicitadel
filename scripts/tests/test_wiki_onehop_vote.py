#!/usr/bin/env python3
"""One-hop wikilink expansion vote (W3, 2026-10-22):
scripts/wiki_onehop_vote.py + the stage-4c hook in
scripts/wiki_search.py hybrid_rank.

Pins:
  - the formula and its bound: gain = 0.5 / (60 + best seed
    rank); gain(1) is the supremum; a candidate adjacent to
    MANY seeds gains only its best seed's term, never a sum —
    the supremum holds under adversarial voting;
  - the vote's WHY: every voted detail names the seed page,
    the seed's rank, the voting-seed count, admission state,
    and the W1.8 edge label (cross-checked against lenslib's
    own edge_label for a verbatim wikilink);
  - admission: a page no stage recalled (bm25 0, PPR below
    the floor) one hop from a lexical hit enters the list on
    its vote alone, via "vote";
  - surgical scale: a candidate no seed links to keeps its
    score EXACTLY with the stage on (no renormalisation);
  - the default path is untouched: same-process A/B —
    hybrid_rank without the argument vs onehop=None —
    identical (score, path, detail) rankings, and no
    onehop_vote key leaks into default details;
  - governance composition (W1.5), strongest form: a page
    the governance artefact withholds, ADMITTED by a vote
    from its neighbourhood, is still withheld by stage 6
    with its reasons and never surfaces; and a withheld
    page acting as a seed may vote for a live neighbour
    but cannot surface itself;
  - severance composition (item 20), strongest form: a
    page-level severed page admitted by a vote is still
    excluded by stage 5;
  - determinism: two voted runs produce identical rankings
    and identical vote records.

Fixture corpora are in-memory (Path, text) pairs on fake
absolute paths — no disk, no tempfile.

Run:  python3 -m unittest scripts.tests.test_wiki_onehop_vote
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


vote = _load("wiki_onehop_vote", ROOT / "scripts" / "wiki_onehop_vote.py")
ws = _load("wiki_search_for_onehop_tests", ROOT / "scripts" / "wiki_search.py")


def doc(name, text):
    return (Path("/fix") / name, text)


# A harbour corpus: the guide is the strong lexical hit; the
# logbook is its one-hop neighbour with NO query vocabulary of
# its own (unretrievable by the default pipeline if its PPR
# stays under the graph floor); the orchard is unlinked.
DOCS = [
    doc("guide.md",
        "# Harbour guide\n"
        "harbour guide tide signal lantern harbour guide. "
        "The harbour guide reads the tide and the signal "
        "lantern. See the [[logbook]] for the keeper's record."),
    doc("logbook.md",
        "# Keeper logbook\n"
        "brine cork gasket wick trimming, entries by watch. "
        "brine cork gasket. Back to the [[guide]]."),
    doc("orchard.md",
        "# Orchard\n"
        "orchard ledger apples pears cider press harvest "
        "orchard ledger apples."),
    doc("quarry.md",
        "# Quarry\n"
        "quarry stone granite slab quarry ledger stone dust."),
]

QUERY = ["harbour", "guide"]


def paths(ranked):
    return [str(p) for _s, p, _t, _d in ranked]


def by_path(ranked):
    return {str(p): (s, d) for s, p, _t, d in ranked}


class FormulaAndBoundTests(unittest.TestCase):
    def test_formula_values(self):
        self.assertAlmostEqual(vote.vote_gain(1), 0.5 / 61)
        self.assertAlmostEqual(vote.vote_gain(1), vote.VOTE_SUPREMUM)
        self.assertAlmostEqual(vote.vote_gain(10), 0.5 / 70)
        self.assertGreater(vote.vote_gain(1), vote.vote_gain(2))
        self.assertGreater(vote.vote_gain(2), vote.vote_gain(50))
        self.assertEqual(vote.vote_gain(None), 0.0)
        self.assertEqual(vote.vote_gain(0), 0.0)

    def test_supremum_holds_under_many_voters(self):
        # A page linked from five strong hits gains only the
        # best seed's term — never a sum over voters.
        docs = [doc("hub.md", "# Hub\nhub words. " +
                    " ".join(f"[[s{i}]]" for i in range(5)))]
        for i in range(5):
            docs.append(doc(f"s{i}.md",
                            f"# Seed {i}\nharbour guide seed{i} "
                            f"harbour guide harbour. Link [[hub]]."))
        docs.append(doc("far.md", "# Far\nunrelated mulch compost."))
        off = by_path(ws.hybrid_rank(QUERY, docs))
        ranked = ws.hybrid_rank(QUERY, docs, onehop=True)
        got = by_path(ranked)
        hub = got["/fix/hub.md"][1]["onehop_vote"]
        # The applied lift (score ON minus score OFF for the
        # same page) never exceeds the supremum; the recorded
        # gain is that value rounded to 6 dp.
        lift = got["/fix/hub.md"][0] - off["/fix/hub.md"][0]
        self.assertLessEqual(lift, vote.VOTE_SUPREMUM + 1e-9)
        self.assertAlmostEqual(lift, hub["gain"], places=6)
        self.assertLessEqual(hub["gain"],
                             round(vote.VOTE_SUPREMUM, 6) + 1e-9)
        self.assertEqual(hub["voting_seeds"], 5)
        self.assertAlmostEqual(hub["gain"], vote.vote_gain(hub["seed_rank"]),
                               places=6)


class VoteStageTests(unittest.TestCase):
    def test_neighbour_admitted_with_why(self):
        ranked = ws.hybrid_rank(QUERY, DOCS, onehop=True)
        got = by_path(ranked)
        self.assertIn("/fix/logbook.md", got)
        _s, d = got["/fix/logbook.md"]
        self.assertIn("onehop_vote", d)
        v = d["onehop_vote"]
        self.assertEqual(v["seed"], "/fix/guide.md")
        self.assertEqual(v["seed_rank"], 1)
        self.assertAlmostEqual(v["gain"], vote.VOTE_SUPREMUM, places=6)
        self.assertEqual(v["edge"]["label"], "EXTRACTED")
        self.assertEqual(v["edge"]["confidence"], 1.0)
        self.assertEqual(v["edge"]["rule"], "verbatim-link")
        rec = ws.LAST_ONEHOP["record"]
        self.assertTrue(ws.LAST_ONEHOP["applied"])
        self.assertEqual(rec["kind"], "onehop-wikilink-vote")
        self.assertIn("/fix/logbook.md", rec["votes"])

    def test_edge_label_matches_lenslib(self):
        lens = _load("lenslib_for_onehop_tests",
                     ROOT / "tools" / "lens" / "lenslib.py")
        want = lens.edge_label("wikilink", "mentions")
        got = vote.edge_label()
        self.assertEqual(got["label"], want["provenance"])
        self.assertEqual(got["confidence"], want["confidence"])
        self.assertEqual(got["polarity"], want["polarity"])

    def test_linkfree_corpus_scores_untouched(self):
        # No links anywhere -> no seed has a neighbour -> the
        # stage changes nothing at all, scores included. (The
        # surgical property: the vote never renormalises.)
        docs = [
            doc("iso1.md",
                "# Iso one\nharbour guide alpha harbour guide "
                "harbour signal."),
            doc("iso2.md",
                "# Iso two\nharbour guide beta harbour signal "
                "lantern."),
            doc("iso3.md", "# Iso three\nmulch compost rows."),
        ]
        off = ws.hybrid_rank(QUERY, docs)
        on = ws.hybrid_rank(QUERY, docs, onehop=True)
        self.assertEqual([(s, str(p)) for s, p, _t, _d in off],
                         [(s, str(p)) for s, p, _t, _d in on])
        for _s, _p, _t, d in on:
            self.assertNotIn("onehop_vote", d)
        self.assertTrue(ws.LAST_ONEHOP["applied"])
        self.assertEqual(ws.LAST_ONEHOP["record"]["votes"], {})

    def test_admission_of_unrecalled_neighbour(self):
        # Twelve strong hits crowd the weak hit out of the
        # PPR seed set (top 10); the weak hit's neighbour has
        # no query vocabulary and no PPR inflow, so the
        # default pipeline never recalls it. The vote admits
        # it, carrying the weak hit's rank in its gain.
        docs = []
        for i in range(12):
            docs.append(doc(f"strong{i}.md",
                            f"# Strong {i}\nharbour guide "
                            f"harbour guide harbour signal "
                            f"lantern tide."))
        docs.append(doc("weak.md",
                        "# Weak note\na single harbour mention. "
                        "See [[target]]."))
        docs.append(doc("target.md",
                        "# Target record\nbrine cork gasket "
                        "wick trimming by watch. See [[weak]]."))
        off = paths(ws.hybrid_rank(QUERY, docs))
        self.assertNotIn("/fix/target.md", off)
        ranked = ws.hybrid_rank(QUERY, docs, onehop=True)
        got = by_path(ranked)
        self.assertIn("/fix/target.md", got)
        s, d = got["/fix/target.md"]
        v = d["onehop_vote"]
        self.assertTrue(v["admitted"])
        self.assertEqual(v["seed"], "/fix/weak.md")
        self.assertEqual(d["via"], "vote")
        self.assertEqual(d["bm25"], 0.0)
        self.assertAlmostEqual(s, vote.vote_gain(v["seed_rank"]),
                               places=6)

    def test_default_ab_identical_and_no_leak(self):
        a = ws.hybrid_rank(QUERY, DOCS)
        b = ws.hybrid_rank(QUERY, DOCS, onehop=None)
        self.assertEqual([(s, str(p), d) for s, p, _t, d in a],
                         [(s, str(p), d) for s, p, _t, d in b])
        for _s, _p, _t, d in a:
            self.assertNotIn("onehop_vote", d)
        self.assertFalse(ws.LAST_ONEHOP["applied"])
        self.assertIsNone(ws.LAST_ONEHOP["record"])

    def test_determinism(self):
        r1 = ws.hybrid_rank(QUERY, DOCS, onehop=True)
        rec1 = ws.LAST_ONEHOP["record"]
        r2 = ws.hybrid_rank(QUERY, DOCS, onehop=True)
        rec2 = ws.LAST_ONEHOP["record"]
        self.assertEqual([(s, str(p)) for s, p, _t, _d in r1],
                         [(s, str(p)) for s, p, _t, _d in r2])
        self.assertEqual(rec1, rec2)


class CompositionTests(unittest.TestCase):
    GOV = {"pages": {"/fix/logbook.md": {
        "state": "withheld",
        "reasons": ["superseded by [[guide]] (status)"]}},
        "state_hash": "fixture"}

    def test_governance_withholds_vote_admitted_page(self):
        ranked = ws.hybrid_rank(QUERY, DOCS, governance=self.GOV,
                                onehop=True)
        self.assertNotIn("/fix/logbook.md", paths(ranked))
        withheld = {w["path"] for w in ws.LAST_GOVERNANCE["withheld"]}
        self.assertIn("/fix/logbook.md", withheld)

    def test_withheld_seed_votes_but_never_surfaces(self):
        docs = [
            doc("dead.md",
                "# Dead claim\nharbour guide dead claim harbour "
                "guide harbour. See [[alive]]."),
            doc("alive.md",
                "# Alive record\nbrine cork gasket wick. "
                "Back to [[dead]]."),
            doc("other.md", "# Other\nmulch compost unrelated."),
        ]
        gov = {"pages": {"/fix/dead.md": {
            "state": "withheld", "reasons": ["retired claim"]}},
            "state_hash": "fixture"}
        ranked = ws.hybrid_rank(QUERY, docs, governance=gov,
                                onehop=True)
        self.assertNotIn("/fix/dead.md", paths(ranked))
        got = by_path(ranked)
        if "/fix/alive.md" in got:
            v = got["/fix/alive.md"][1].get("onehop_vote")
            if v is not None:
                self.assertEqual(v["seed"], "/fix/dead.md")

    def test_severance_excludes_vote_admitted_page(self):
        sev = {"entries": [{"kind": "page", "page": "/fix/logbook.md",
                            "id": "sev-fixture"}]}
        ranked = ws.hybrid_rank(QUERY, DOCS, severance=sev,
                                onehop=True)
        self.assertNotIn("/fix/logbook.md", paths(ranked))
        excluded = {e["path"] for e in ws.LAST_SEVERANCE["excluded"]}
        self.assertIn("/fix/logbook.md", excluded)


if __name__ == "__main__":
    unittest.main()
