#!/usr/bin/env python3
"""FalkorDB-pattern CSR sparse-matrix graph export (Marathon
Round 3, lane TB7, row 10c).

Pins on a hand-built graph dict: build_csr emits shape /
node_ids / indptr / indices / values in the graph's node order;
the matrix reconstructs the emitted adjacency EXACTLY
(out-neighbours per row, parallel edges preserved); an empty
graph and an isolated node are handled; the CSR is
deterministic.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_graph_export_csr", ROOT / "scripts" / "wiki_graph_export.py")
GE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GE)

GRAPH = {
    "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
    "edges": [
        {"source": "a", "target": "b"},
        {"source": "a", "target": "c"},
        {"source": "a", "target": "b"},   # parallel edge: kept
        {"source": "b", "target": "a"},
        {"source": "c", "target": "c"},   # self-loop: kept
    ],
}


def rows_of(csr):
    ids = csr["node_ids"]
    rows = {}
    for r, nid in enumerate(ids):
        lo, hi = csr["indptr"][r], csr["indptr"][r + 1]
        rows[nid] = [ids[j] for j in csr["indices"][lo:hi]]
    return rows


class CsrTests(unittest.TestCase):
    def test_shape_and_pointers(self):
        csr = GE.build_csr(GRAPH)
        self.assertEqual(csr["format"], "csr")
        self.assertEqual(csr["shape"], [4, 4])
        self.assertEqual(csr["node_ids"], ["a", "b", "c", "d"])
        self.assertEqual(csr["indptr"], [0, 3, 4, 5, 5])
        self.assertEqual(len(csr["indices"]), 5)
        self.assertEqual(csr["values"], [1] * 5)
        self.assertEqual(csr["indptr"][-1], len(GRAPH["edges"]))

    def test_adjacency_reconstructs(self):
        self.assertEqual(rows_of(GE.build_csr(GRAPH)), {
            "a": ["b", "b", "c"], "b": ["a"], "c": ["c"], "d": []})

    def test_empty_and_deterministic(self):
        empty = GE.build_csr({"nodes": [], "edges": []})
        self.assertEqual(empty["shape"], [0, 0])
        self.assertEqual(empty["indptr"], [0])
        self.assertEqual(GE.build_csr(GRAPH), GE.build_csr(GRAPH))


if __name__ == "__main__":
    unittest.main()
