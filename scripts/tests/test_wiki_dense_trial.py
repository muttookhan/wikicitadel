#!/usr/bin/env python3
"""The dense retrieval TRIAL lane (W1.2, 2026-10-22):
scripts/wiki_dense_trial.py.

Pins, on fixture corpora (never the live corpus, never the
golden/extended question files):

  - RRF fusion MATH: a fused score is exactly the sum of
    1/(k + rank) over the legs the path appears in, k = 60 by
    default; ordering is by (-score, path) so ties are
    deterministic; a path in both legs outscores a path at the
    same rank in one leg, and adding a leg never lowers a score;
  - the SVD (LSA) embedder separates the fixture's two topics:
    same-topic cosine beats cross-topic cosine for document
    vectors, and a folded-in topic query lands on a topic page;
    fitting twice gives byte-identical vectors (determinism,
    including the sign fix);
  - the hashing embedder is deterministic, unit-norm, and SWAPS
    through the same projection interface as the SVD embedder
    (the interface-swap pin);
  - the projection REBUILDS reproducibly: two builds over the
    same fixture corpus produce identical vectors-table BLOBs
    and the same corpus hash;
  - the store's two legs behave: FTS5 ranks the distinctive-term
    page first, dense ranks a topic page first, and a serialised
    file image round-trips through ProjectionStore;
  - frontmatter parsing takes title/type and tolerates absence.

File-backed steps use a scratch dir under scripts/tests/ (this
suite avoids tempfile on purpose: some sandboxes deny its
probe); a step whose file writes the environment refuses is
skipped with the reason, never silently passed.

Run:  python3 -m unittest scripts.tests.test_wiki_dense_trial
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(__file__).resolve().parent / ".dense-trial-scratch"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dt = _load("wiki_dense_trial", "scripts/wiki_dense_trial.py")
ws = _load("wiki_search", "scripts/wiki_search.py")

FIXTURE_DOCS = [
    (Path("wiki/cats.md"),
     "---\ntitle: Cats\ntype: note\n---\n"
     "cat kitten purr feline cat kitten whiskers purr"),
    (Path("wiki/cats-two.md"),
     "---\ntitle: More cats\ntype: note\n---\n"
     "kitten cat feline whiskers purr kitten"),
    (Path("wiki/databases.md"),
     "---\ntitle: Databases\ntype: note\n---\n"
     "database index query sql database table index"),
    (Path("wiki/databases-two.md"),
     "database sql query table database index sql"),
    (Path("wiki/cooking.md"),
     "recipe oven bake flour sugar oven recipe"),
    (Path("wiki/baking.md"),
     "bake recipe flour sugar oven recipe bake"),
]


def _tokens(docs):
    return [ws.tokenize(text) for _p, text in docs]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


class RrfTests(unittest.TestCase):
    def test_scores_are_exact_rrf(self):
        fused = dt.rrf_scores([["a", "b", "c"], ["b", "a"]], k=60)
        self.assertAlmostEqual(fused["a"], 1 / 61 + 1 / 62)
        self.assertAlmostEqual(fused["b"], 1 / 62 + 1 / 61)
        self.assertAlmostEqual(fused["c"], 1 / 63)

    def test_both_legs_beat_one_leg_at_same_rank(self):
        fused = dt.rrf_scores([["x", "y"], ["x"]], k=60)
        self.assertGreater(fused["x"], 1 / 61)
        solo = dt.rrf_scores([["x", "y"]], k=60)
        self.assertGreaterEqual(fused["y"], solo["y"])

    def test_ordering_deterministic_on_ties(self):
        out = dt.rrf_fuse([["b"], ["a"]], k=60)
        self.assertEqual([p for p, _s in out], ["a", "b"])


class SvdEmbedderTests(unittest.TestCase):
    def setUp(self):
        self.emb = dt.SvdEmbedder().fit(_tokens(FIXTURE_DOCS))
        self.vecs = self.emb.doc_vectors()

    def test_same_topic_beats_cross_topic(self):
        cats, cats2, db = self.vecs[0], self.vecs[1], self.vecs[2]
        self.assertGreater(_cos(cats, cats2), _cos(cats, db))

    def test_query_foldin_lands_on_topic(self):
        q = self.emb.embed_tokens(ws.tokenize("cat kitten"))
        best = max(range(len(self.vecs)),
                   key=lambda i: _cos(q, self.vecs[i]))
        self.assertIn(best, (0, 1))
        q2 = self.emb.embed_tokens(ws.tokenize("sql database"))
        best2 = max(range(len(self.vecs)),
                    key=lambda i: _cos(q2, self.vecs[i]))
        self.assertIn(best2, (2, 3))

    def test_deterministic_refit(self):
        again = dt.SvdEmbedder().fit(_tokens(FIXTURE_DOCS))
        self.assertEqual(self.vecs, again.doc_vectors())
        self.assertEqual(self.emb.components, again.components)

    def test_unit_norm(self):
        for v in self.vecs:
            self.assertAlmostEqual(_cos(v, v), 1.0, places=9)


class HashingEmbedderTests(unittest.TestCase):
    def test_deterministic_and_unit_norm(self):
        toks = _tokens(FIXTURE_DOCS)
        a = dt.HashingEmbedder().fit(toks)
        b = dt.HashingEmbedder().fit(toks)
        self.assertEqual(a.doc_vectors(), b.doc_vectors())
        for v in a.doc_vectors():
            self.assertAlmostEqual(_cos(v, v), 1.0, places=9)
        self.assertEqual(a.state_tables(), ([], []))


class ProjectionTests(unittest.TestCase):
    def _build_memory(self, embedder):
        conn = sqlite3.connect(":memory:")
        meta = dt.build_projection_conn(conn, embedder, FIXTURE_DOCS, ws)
        return conn, meta

    def test_rebuild_reproduces_vectors_byte_for_byte(self):
        blobs = []
        hashes = []
        for _ in range(2):
            conn, meta = self._build_memory(dt.SvdEmbedder())
            blobs.append(conn.execute(
                "SELECT path, vec FROM vectors ORDER BY path").fetchall())
            hashes.append(meta["corpus_hash"])
            conn.close()
        self.assertEqual(blobs[0], blobs[1])
        self.assertEqual(hashes[0], hashes[1])

    def test_fts_leg_finds_distinctive_term(self):
        conn, _meta = self._build_memory(dt.SvdEmbedder())
        store = dt.ProjectionStore(conn)
        ranked = store.fts_rank(ws.tokenize("sql query"))
        self.assertEqual(ranked[0][1], "wiki/databases-two.md")
        store.close()

    def test_dense_leg_finds_topic(self):
        conn, _meta = self._build_memory(dt.SvdEmbedder())
        store = dt.ProjectionStore(conn)
        ranked = store.dense_rank(ws.tokenize("kitten purr"))
        self.assertIn(ranked[0][1], ("wiki/cats.md", "wiki/cats-two.md"))
        store.close()

    def test_interface_swap_hashing_embedder(self):
        conn, meta = self._build_memory(dt.HashingEmbedder())
        self.assertEqual(meta["embedder"], "hashing")
        store = dt.ProjectionStore(conn)
        ranked = store.dense_rank(ws.tokenize("database index"))
        self.assertTrue(ranked)
        self.assertIn(ranked[0][1],
                      ("wiki/databases.md", "wiki/databases-two.md"))
        store.close()

    def test_frontmatter_lands_in_docs_table(self):
        conn, _meta = self._build_memory(dt.SvdEmbedder())
        row = conn.execute(
            "SELECT title, type FROM docs WHERE path = 'wiki/cats.md'"
        ).fetchone()
        self.assertEqual(row, ("Cats", "note"))
        row2 = conn.execute(
            "SELECT title, type FROM docs "
            "WHERE path = 'wiki/databases-two.md'").fetchone()
        self.assertEqual(row2, ("", ""))
        conn.close()

    def test_file_image_round_trip(self):
        SCRATCH.mkdir(exist_ok=True)
        db = SCRATCH / "projection.sqlite"
        try:
            dt.build_projection(db, dt.SvdEmbedder(),
                                docs=FIXTURE_DOCS, ws=ws)
        except (PermissionError, sqlite3.OperationalError) as exc:
            self.skipTest("environment refuses the projection "
                          "file write: %s" % exc)
        store = dt.ProjectionStore(db)
        self.assertEqual(store.meta["corpus_docs"], "6")
        ranked = store.dense_rank(ws.tokenize("kitten purr"))
        self.assertIn(ranked[0][1], ("wiki/cats.md", "wiki/cats-two.md"))
        store.close()

    def tearDown(self):
        if SCRATCH.exists():
            shutil.rmtree(SCRATCH, ignore_errors=True)


class FrontmatterTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            dt.parse_frontmatter("---\ntitle: Hi\ntype: note\n---\nx"),
            ("Hi", "note"))
        self.assertEqual(dt.parse_frontmatter("no frontmatter"),
                         ("", ""))


if __name__ == "__main__":
    unittest.main()
