#!/usr/bin/env python3
"""W1.7: Lens graph analytics pack — the graphology algorithm
family re-implemented in tools/lens/lenslib.py: full two-phase
Louvain + modularity, the centrality suite (PageRank, Brandes
betweenness, Wasserman–Faust closeness, eigenvector, clustering),
graph-level metrics, the Adamic-Adar / Common Neighbours link
prediction pack, and per-cluster digests crawled over links and
backlinks to a chosen depth.

The fixture graphs have hand-computed answers (two triangles and
a bridge; a star; a path), and every function is pinned for
determinism: same fixture in => identical structure out, twice.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def pair(a, b):
    return (a, b) if a < b else (b, a)


# Two triangles joined by a single bridge edge c-d. Hand-computed:
# degrees a2 b2 c3 d3 e2 f2; total weight 7.
TRI_NODES = ["a", "b", "c", "d", "e", "f"]
TRI_W = {pair(*e): 1.0 for e in
         [("a", "b"), ("b", "c"), ("a", "c"),
          ("d", "e"), ("e", "f"), ("d", "f"), ("c", "d")]}
TRI_PART = {"a": 0, "b": 0, "c": 0, "d": 1, "e": 1, "f": 1}

STAR_NODES = ["s", "l1", "l2", "l3", "l4"]
STAR_W = {pair("s", leaf): 1.0 for leaf in STAR_NODES[1:]}


class TestLouvainFull(unittest.TestCase):
    def test_two_triangles_stay_apart(self):
        part = L.louvain_full(TRI_NODES, TRI_W)
        groups = {}
        for node, cid in part.items():
            groups.setdefault(cid, set()).add(node)
        self.assertEqual({frozenset(g) for g in groups.values()},
                         {frozenset("abc"), frozenset("def")})

    def test_renumbered_by_smallest_member(self):
        part = L.louvain_full(TRI_NODES, TRI_W)
        self.assertEqual(part["a"], 0)
        self.assertEqual(part["d"], 1)

    def test_isolated_node_is_its_own_community(self):
        part = L.louvain_full(TRI_NODES + ["zz"], TRI_W)
        self.assertNotIn(part["zz"], (part["a"], part["d"]))
        self.assertEqual(len(part), 7)

    def test_no_edges_each_node_alone(self):
        part = L.louvain_full(["x", "y"], {})
        self.assertEqual(len(set(part.values())), 2)

    def test_deterministic(self):
        self.assertEqual(L.louvain_full(TRI_NODES, TRI_W),
                         L.louvain_full(TRI_NODES, TRI_W))

    def test_clique_merges_to_one(self):
        nodes = ["a", "b", "c"]
        w = {pair(*e): 1.0 for e in
             [("a", "b"), ("b", "c"), ("a", "c")]}
        part = L.louvain_full(nodes, w)
        self.assertEqual(len(set(part.values())), 1)

    def test_heavy_bridge_reorganises(self):
        # A bridge of weight 10 does NOT merge the triangles into
        # one community — modularity prefers pairing the two
        # bridgeheads and leaving each far pair together:
        # {a,b} {c,d} {e,f} at Q = 0.15625, against Q = 0 for one
        # community and Q < 0 for the two-triangle split.
        w = dict(TRI_W)
        w[pair("c", "d")] = 10.0
        part = L.louvain_full(TRI_NODES, w)
        groups = {}
        for node, cid in part.items():
            groups.setdefault(cid, set()).add(node)
        self.assertEqual({frozenset(g) for g in groups.values()},
                         {frozenset("ab"), frozenset("cd"),
                          frozenset("ef")})


class TestModularity(unittest.TestCase):
    def test_triangle_partition_value(self):
        # Q = 2 * (3/7 - (7/14)^2) = 0.357142...
        q = L.modularity(TRI_NODES, TRI_W, TRI_PART)
        self.assertAlmostEqual(q, 2 * (3 / 7 - 0.25), places=9)

    def test_one_community_is_zero(self):
        q = L.modularity(TRI_NODES, TRI_W,
                         {n: 0 for n in TRI_NODES})
        self.assertAlmostEqual(q, 0.0, places=9)

    def test_singletons_are_negative(self):
        part = {n: i for i, n in enumerate(TRI_NODES)}
        self.assertLess(L.modularity(TRI_NODES, TRI_W, part), 0.0)

    def test_edgeless_is_zero(self):
        self.assertEqual(L.modularity(["x"], {}, {"x": 0}), 0.0)


class TestCentralities(unittest.TestCase):
    def test_star_betweenness(self):
        cen = L.graph_centralities(STAR_NODES, STAR_W)
        self.assertAlmostEqual(cen["s"]["betweenness"], 1.0, places=9)
        for leaf in STAR_NODES[1:]:
            self.assertAlmostEqual(cen[leaf]["betweenness"], 0.0,
                                   places=9)

    def test_star_pagerank_and_degree(self):
        cen = L.graph_centralities(STAR_NODES, STAR_W)
        self.assertGreater(cen["s"]["pagerank"], cen["l1"]["pagerank"])
        self.assertAlmostEqual(cen["s"]["degree_centrality"], 1.0)
        self.assertAlmostEqual(cen["l1"]["degree_centrality"], 0.25)
        self.assertAlmostEqual(
            sum(c["pagerank"] for c in cen.values()), 1.0, places=6)

    def test_star_closeness(self):
        cen = L.graph_centralities(STAR_NODES, STAR_W)
        self.assertAlmostEqual(cen["s"]["closeness"], 1.0, places=9)
        # Leaf: reaches 4 nodes, distance sum 1+2+2+2 = 7 -> 4/7.
        self.assertAlmostEqual(cen["l1"]["closeness"], 4 / 7, places=9)

    def test_star_clustering_is_zero(self):
        cen = L.graph_centralities(STAR_NODES, STAR_W)
        for node in STAR_NODES:
            self.assertEqual(cen[node]["clustering"], 0.0)

    def test_triangle_clustering_is_one(self):
        nodes = ["a", "b", "c"]
        w = {pair(*e): 2.0 for e in
             [("a", "b"), ("b", "c"), ("a", "c")]}
        cen = L.graph_centralities(nodes, w)
        for node in nodes:
            self.assertAlmostEqual(cen[node]["clustering"], 1.0)
            self.assertAlmostEqual(cen[node]["clustering_weighted"],
                                   1.0)

    def test_bridge_nodes_carry_the_betweenness(self):
        cen = L.graph_centralities(TRI_NODES, TRI_W)
        for node in ("a", "b", "e", "f"):
            self.assertAlmostEqual(cen[node]["betweenness"], 0.0,
                                   places=9)
        self.assertGreater(cen["c"]["betweenness"], 0.0)
        self.assertGreater(cen["d"]["betweenness"], 0.0)

    def test_eigenvector_positive_and_ranked(self):
        cen = L.graph_centralities(TRI_NODES, TRI_W)
        self.assertTrue(all(c["eigenvector"] >= 0.0
                            for c in cen.values()))
        self.assertGreater(cen["c"]["eigenvector"],
                           cen["a"]["eigenvector"])

    def test_deterministic(self):
        self.assertEqual(L.graph_centralities(TRI_NODES, TRI_W),
                         L.graph_centralities(TRI_NODES, TRI_W))


class TestGraphLevelMetrics(unittest.TestCase):
    def test_two_triangles(self):
        m = L.graph_level_metrics(TRI_NODES, TRI_W, TRI_PART)
        self.assertEqual(m["nodes"], 6)
        self.assertEqual(m["edges"], 7)
        self.assertAlmostEqual(m["density"], 14 / 30, places=9)
        self.assertEqual(m["components"], 1)
        self.assertEqual(m["diameter"], 3)
        self.assertEqual(m["radius"], 2)
        # Clustering: corners 1, bridgeheads 1/3 -> mean 7/9.
        self.assertAlmostEqual(m["average_clustering"], 7 / 9,
                               places=9)
        self.assertAlmostEqual(m["modularity"],
                               2 * (3 / 7 - 0.25), places=9)

    def test_disconnected_components(self):
        m = L.graph_level_metrics(STAR_NODES + ["zz"], STAR_W)
        self.assertEqual(m["components"], 2)
        self.assertEqual(m["component_sizes"], [5, 1])


class TestLinkPredictionPack(unittest.TestCase):
    # (a, b) share ONE rare neighbour (degree 2): Adamic-Adar's
    # pick. (c, d) share THREE hub neighbours (degree 10 each):
    # Common Neighbours' pick. The lanes must part ways.
    def _neighbours(self):
        nb = {"a": {"g"}, "b": {"g"}, "g": {"a", "b"},
              "c": set(), "d": set()}
        for i, h in enumerate(("h1", "h2", "h3")):
            fillers = {f"f{i}_{j}" for j in range(8)}
            nb[h] = {"c", "d"} | fillers
            nb["c"].add(h)
            nb["d"].add(h)
            for f in fillers:
                nb[f] = {h}
        # c and d are hubs in their own right (degree 11), so the
        # hub pair (h1, h2) — which shares only c and d — scores
        # 2/ln(11) under Adamic-Adar and cannot outrank (a, b).
        for leaf in ("c", "d"):
            privates = {f"{leaf}_{j}" for j in range(8)}
            nb[leaf] |= privates
            for f in privates:
                nb[f] = {leaf}
        return nb

    def test_lanes_part_ways(self):
        pack = L.link_prediction_pack(self._neighbours())
        self.assertEqual((pack["by_adamic_adar"][0]["a"],
                          pack["by_adamic_adar"][0]["b"]), ("a", "b"))
        self.assertAlmostEqual(pack["by_adamic_adar"][0]["adamic_adar"],
                               1 / math.log(2), places=4)
        self.assertEqual(pack["by_adamic_adar"][0]["common_neighbours"],
                         1)
        top_cn = pack["by_common_neighbours"][0]
        self.assertEqual((top_cn["a"], top_cn["b"]), ("c", "d"))
        self.assertEqual(top_cn["common_neighbours"], 3)
        self.assertAlmostEqual(top_cn["adamic_adar"],
                               3 / math.log(10), places=4)

    def test_adjacent_pairs_never_suggested(self):
        nb = self._neighbours()
        for lane in ("by_adamic_adar", "by_common_neighbours"):
            for entry in L.link_prediction_pack(nb)[lane]:
                self.assertNotIn(entry["b"], nb[entry["a"]])

    def test_deterministic(self):
        nb = self._neighbours()
        self.assertEqual(L.link_prediction_pack(nb),
                         L.link_prediction_pack(nb))


class TestClusterDigests(unittest.TestCase):
    NODES = ["h", "m1", "m2", "x"]
    PART = {"h": 0, "m1": 0, "m2": 0, "x": 1}
    OUT = {"h": {"m1"}, "m1": {"x"}, "m2": {"h"}, "x": set()}
    IN = {"h": {"m2"}, "m1": {"h"}, "m2": set(), "x": {"m1"}}
    TITLES = {"h": "Hub", "m1": "Member One", "m2": "Member Two",
              "x": "Outside"}
    W = {pair("h", "m1"): 2.0, pair("h", "m2"): 1.0,
         pair("m1", "x"): 3.0}

    def _digests(self, depth=2):
        cocit = {"h": [{"other": "m1", "shared_citers": 2,
                        "sentences": [{"by": "x",
                                       "text": "Hub and One "
                                               "together."}]}]}
        return L.cluster_digests(
            self.NODES, self.PART, self.OUT, self.IN, self.TITLES,
            {"h": "The hub lede."}, self.W, cocitations=cocit,
            depth=depth)

    def test_hub_and_member_ranking(self):
        d0 = self._digests()[0]
        self.assertEqual(d0["hub_id"], "h")
        self.assertEqual([m["id"] for m in d0["members"]],
                         ["h", "m1", "m2"])
        self.assertEqual(d0["label"], "Cluster around Hub")
        self.assertEqual(d0["hub_summary"], "The hub lede.")
        self.assertEqual(d0["size"], 3)
        self.assertEqual(d0["members_omitted"], 0)

    def test_crawl_uses_backlinks_and_records_depth(self):
        d0 = self._digests(depth=1)[0]
        depths = {m["id"]: m["depth"] for m in d0["members"]}
        # m2 reaches the hub only through its own out-link (a
        # backlink of the hub): the crawl walks both directions.
        self.assertEqual(depths, {"h": 0, "m1": 1, "m2": 1})
        self.assertEqual(d0["crawl_depth"], 1)
        self.assertEqual(d0["unreached"], 0)

    def test_shallow_crawl_leaves_members_unreached(self):
        d0 = self._digests(depth=0)[0]
        depths = {m["id"]: m["depth"] for m in d0["members"]}
        self.assertEqual(depths["h"], 0)
        self.assertIsNone(depths["m1"])
        self.assertEqual(d0["unreached"], 2)

    def test_boundary_edges_point_outside(self):
        d0 = self._digests()[0]
        self.assertEqual(len(d0["boundary"]), 1)
        edge = d0["boundary"][0]
        self.assertEqual((edge["from"], edge["to"]), ("m1", "x"))
        self.assertEqual(edge["to_title"], "Outside")
        self.assertEqual(edge["weight"], 3.0)

    def test_internal_edges_ranked_by_weight(self):
        d0 = self._digests()[0]
        self.assertEqual(
            [(e["a"], e["b"]) for e in d0["top_internal_edges"]],
            [("h", "m1"), ("h", "m2")])

    def test_cocited_pair_with_sentence(self):
        d0 = self._digests()[0]
        self.assertEqual(d0["cocited_pair"]["a"], "h")
        self.assertEqual(d0["cocited_pair"]["b"], "m1")
        self.assertEqual(d0["cocited_pair"]["shared_citers"], 2)
        self.assertEqual(d0["cocited_pair"]["sentence"],
                         "Hub and One together.")
        self.assertEqual(d0["cocited_pair"]["cited_by"], "x")

    def test_deterministic(self):
        self.assertEqual(self._digests(), self._digests())


if __name__ == "__main__":
    unittest.main()
