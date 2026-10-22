"""Wave-2 item W2 (Graphviz-WASM deterministic layout option)
unit tests — run from anywhere:

    python3 -m unittest tools.lens.tests.test_graphlayout
    python3 tools/lens/tests/test_graphlayout.py

The named engine (@hpcc-js/wasm-graphviz) is not available on
this machine, so these tests cover the house layered engine that
ships behind the same interface (graphlayout.py states the door
and the engine reality in its header). Covered: the rank rule
(longest path; a DAG edge always runs from a lower rank to a
higher one, and an input edge that does not is exactly a
reported reversed edge), cycle breaking, crossing reduction by
the barycenter sweeps, input hygiene (duplicates, self-loops,
edges to unknown nodes), the centred coordinate rule and canvas
margins, and the item's core property — determinism: identical
inputs give byte-identical positions, and the input sequence's
order changes nothing.
"""

import json
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))

import graphlayout as GL  # noqa: E402


def ranks_by_y(positions):
    """Recover each node's rank order from its y coordinate
    (rank 0 is the top layer, smallest y)."""
    ys = sorted({p[1] for p in positions.values()})
    return {n: ys.index(p[1]) for n, p in positions.items()}


class TestRanks(unittest.TestCase):
    def test_chain_layers_in_order(self):
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "c", "d"],
            [("a", "b"), ("b", "c"), ("c", "d")])
        self.assertEqual(rep["ranks"], 4)
        self.assertEqual(rep["rank_sizes"], [1, 1, 1, 1])
        r = ranks_by_y(pos)
        self.assertEqual([r[n] for n in "abcd"], [0, 1, 2, 3])
        # One node per rank: every x is the canvas centre.
        self.assertTrue(all(p[0] == 500.0 for p in pos.values()))

    def test_diamond(self):
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "c", "d"],
            [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        r = ranks_by_y(pos)
        self.assertEqual(r["a"], 0)
        self.assertEqual({r["b"], r["c"]}, {1})
        self.assertEqual(r["d"], 2)
        self.assertEqual(rep["reversed_edges"], [])

    def test_long_edge_uses_longest_path(self):
        # a -> d directly AND via b: d's rank is set by the
        # longest path, so the direct edge spans two ranks.
        pos, _ = GL.hierarchical_layout(
            ["a", "b", "d"],
            [("a", "d"), ("a", "b"), ("b", "d")])
        r = ranks_by_y(pos)
        self.assertEqual(r["d"], 2)

    def test_isolated_node_rank_zero_and_positioned(self):
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "lonely"], [("a", "b")])
        self.assertEqual(set(pos), {"a", "b", "lonely"})
        self.assertEqual(ranks_by_y(pos)["lonely"], 0)
        self.assertEqual(rep["ranks"], 2)

    def test_every_dag_edge_runs_downhill(self):
        edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"),
                 ("a", "d"), ("d", "b")]
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "c", "d"], edges)
        r = ranks_by_y(pos)
        reversed_set = {tuple(e) for e in rep["reversed_edges"]}
        for a, b in edges:
            if (a, b) in reversed_set:
                # The DAG keeps b -> a instead, so a sits
                # strictly below b.
                self.assertGreater(r[a], r[b])
            else:
                self.assertGreater(r[b], r[a])


class TestCycles(unittest.TestCase):
    def test_cycle_is_broken_and_reported(self):
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "c"],
            [("a", "b"), ("b", "c"), ("c", "a")])
        self.assertEqual(len(rep["reversed_edges"]), 1)
        self.assertEqual(rep["dag_edges"], 3)
        self.assertEqual(rep["ranks"], 3)

    def test_self_loop_and_duplicates_and_unknowns_dropped(self):
        pos, rep = GL.hierarchical_layout(
            ["a", "b"],
            [("a", "a"), ("a", "b"), ("a", "b"), ("a", "zzz"),
             ("zzz", "b")])
        self.assertEqual(rep["directed_edges"], 1)
        self.assertEqual(set(pos), {"a", "b"})


class TestOrdering(unittest.TestCase):
    def test_barycenter_sweeps_uncross_a_crossing(self):
        # Id order in rank 1 is [c, d]; the edges a->d, b->c
        # cross once. The sweeps must reorder rank 1 to [d, c]
        # and report zero crossings.
        pos, rep = GL.hierarchical_layout(
            ["a", "b", "c", "d"], [("a", "d"), ("b", "c")])
        self.assertEqual(rep["crossings"], 0)
        self.assertLess(pos["d"][0], pos["c"][0])

    def test_positions_inside_canvas_margins(self):
        nodes = ["n%02d" % i for i in range(40)]
        edges = [(nodes[i], nodes[i + 1]) for i in range(39)]
        edges += [(nodes[0], nodes[i]) for i in range(2, 40, 3)]
        pos, _ = GL.hierarchical_layout(nodes, edges)
        for x, y in pos.values():
            self.assertGreaterEqual(x, GL.MARGIN_X - 1)
            self.assertLessEqual(x, 1000 - GL.MARGIN_X + 1)
            self.assertGreaterEqual(y, GL.MARGIN_Y - 1)
            self.assertLessEqual(y, 660 - GL.MARGIN_Y + 1)


class TestDeterminism(unittest.TestCase):
    def _big_graph(self):
        rng = random.Random(20261022)
        nodes = ["page-%03d" % i for i in range(120)]
        edges = set()
        while len(edges) < 400:
            a, b = rng.choice(nodes), rng.choice(nodes)
            if a != b:
                edges.add((a, b))
        return nodes, sorted(edges)

    def test_byte_identical_across_runs(self):
        nodes, edges = self._big_graph()
        p1, r1 = GL.hierarchical_layout(nodes, edges)
        p2, r2 = GL.hierarchical_layout(nodes, edges)
        self.assertEqual(json.dumps(p1, sort_keys=True),
                         json.dumps(p2, sort_keys=True))
        self.assertEqual(json.dumps(r1, sort_keys=True),
                         json.dumps(r2, sort_keys=True))

    def test_input_sequence_order_changes_nothing(self):
        nodes, edges = self._big_graph()
        p1, r1 = GL.hierarchical_layout(nodes, edges)
        p2, r2 = GL.hierarchical_layout(list(reversed(nodes)),
                                        list(reversed(edges)))
        self.assertEqual(json.dumps(p1, sort_keys=True),
                         json.dumps(p2, sort_keys=True))
        self.assertEqual(r1, r2)

    def test_empty_graph(self):
        pos, rep = GL.hierarchical_layout([], [])
        self.assertEqual(pos, {})
        self.assertEqual(rep["ranks"], 0)

    def test_single_rank_centres_vertically(self):
        pos, rep = GL.hierarchical_layout(["x", "y"], [])
        self.assertEqual(rep["ranks"], 1)
        self.assertTrue(all(p[1] == 330.0 for p in pos.values()))


if __name__ == "__main__":
    unittest.main()
