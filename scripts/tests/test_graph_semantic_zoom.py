#!/usr/bin/env python3
"""W2: semantic zoom — the zoom section of tools/lens/lenslib.py
(the multilevel Lens view: overview = one supernode per
community, community = one community expanded into its member
pages, pages = the full graph).

Pinned here: the zoom levels are DERIVED from the rendered
partition passed in — the zoom block's communities partition the
node set exactly (no page in two communities, none lost), and
the community a page lands in is exactly the partition's
assignment (the same one the shipped graph artefact carries on
every node, in the community summaries, and in the cluster
digests); centroids are the mean of member layout positions;
cross-community edges aggregate EVERY weighted relation pair,
not only direct links; plurality type breaks ties by the
legend's group order; an unassigned node is counted, never
silently placed; and the block assembles deterministically
(same inputs — in any dict order — byte-identical JSON).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "lenslib", ROOT / "tools" / "lens" / "lenslib.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

GROUP_ORDER = ["overview", "source", "entity", "concept",
               "synthesis", "query", "other"]
NODES = ["a", "b", "c", "d", "e", "f", "g"]
PARTITION = {"a": 0, "b": 0, "c": 0, "d": 1, "e": 1, "f": 2}
PAIRS = {
    ("a", "b"): {"weight": 3.0, "direct": 1},
    ("a", "c"): {"weight": 1.5, "direct": 0},
    ("b", "d"): {"weight": 2.0, "direct": 1},
    ("c", "e"): {"weight": 0.5, "direct": 0},
    ("d", "e"): {"weight": 4.0, "direct": 1},
    ("d", "f"): {"weight": 1.0, "direct": 0},
    ("a", "g"): {"weight": 9.0, "direct": 1},
}
LAYOUT = {"a": (0, 0), "b": (100, 0), "c": (0, 100),
          "d": (500, 300), "e": (700, 300), "f": (900, 600),
          "g": (50, 50)}
GROUPS = {"a": "entity", "b": "entity", "c": "source",
          "d": "concept", "e": "concept", "f": "query",
          "g": "entity"}
WDEGREES = {"a": 13.5, "b": 5.0, "c": 2.0, "d": 7.0, "e": 4.5,
            "f": 1.0, "g": 9.0}
META = {0: {"label": "Cluster around A", "hub_id": "a",
            "hub_title": "A"},
        1: {"label": "Cluster around D", "hub_id": "d",
            "hub_title": "D"},
        2: {"label": "Cluster around F", "hub_id": "f",
            "hub_title": "F"}}
PAIR_TYPES = {("b", "d"): {"cites"}, ("c", "e"): {"extends"},
              ("d", "f"): {"cites", "mentions"}}


def build(pairs=None, partition=None):
    return L.graph_zoom_levels(
        NODES, PARTITION if partition is None else partition,
        PAIRS if pairs is None else pairs, LAYOUT, GROUPS,
        GROUP_ORDER, WDEGREES, META, PAIR_TYPES)


class PartitionTests(unittest.TestCase):
    def test_levels_partition_the_node_set_exactly(self):
        zoom = build()
        concat = [m for c in zoom["communities"]
                  for m in c["members"]]
        self.assertEqual(sorted(concat), sorted(PARTITION))
        counts = Counter(concat)
        self.assertTrue(all(v == 1 for v in counts.values()))

    def test_assignment_is_exactly_the_partition(self):
        zoom = build()
        for c in zoom["communities"]:
            for m in c["members"]:
                self.assertEqual(PARTITION[m], c["id"])

    def test_unassigned_node_counted_never_placed(self):
        zoom = build()
        self.assertEqual(zoom["counts"]["unassigned_nodes"], 1)
        self.assertEqual(zoom["counts"]["skipped_pairs"], 1)
        placed = {m for c in zoom["communities"]
                  for m in c["members"]}
        self.assertNotIn("g", placed)


class AggregationTests(unittest.TestCase):
    def test_centroid_is_member_mean(self):
        zoom = build()
        by_id = {c["id"]: c for c in zoom["communities"]}
        self.assertEqual((by_id[0]["x"], by_id[0]["y"]),
                         (33.3, 33.3))
        self.assertEqual((by_id[1]["x"], by_id[1]["y"]),
                         (600.0, 300.0))
        self.assertEqual((by_id[2]["x"], by_id[2]["y"]),
                         (900.0, 600.0))

    def test_community_rows(self):
        zoom = build()
        by_id = {c["id"]: c for c in zoom["communities"]}
        self.assertEqual(by_id[0]["members"], ["a", "b", "c"])
        self.assertEqual(by_id[0]["member_count"], 3)
        self.assertEqual(by_id[0]["total_wdegree"], 20.5)
        self.assertEqual(by_id[0]["internal_weight"], 4.5)
        self.assertEqual(by_id[0]["internal_pairs"], 2)
        self.assertEqual(by_id[0]["label"], "Cluster around A")
        self.assertEqual(by_id[0]["hub_id"], "a")
        self.assertEqual(by_id[0]["key"], "community:0")
        self.assertEqual(by_id[1]["internal_weight"], 4.0)
        self.assertEqual(by_id[2]["internal_pairs"], 0)

    def test_cross_edges_aggregate_all_pairs(self):
        zoom = build()
        self.assertEqual(len(zoom["edges"]), 2)
        first, second = zoom["edges"]
        # (0,1): the direct (b,d) pair AND the derived (c,e)
        # pair both count — aggregation is over every weighted
        # relation, not only direct links.
        self.assertEqual((first["a"], first["b"]), (0, 1))
        self.assertEqual(first["weight"], 2.5)
        self.assertEqual(first["pairs"], 2)
        self.assertEqual(first["direct_pairs"], 1)
        self.assertEqual(first["rm_types"], ["cites", "extends"])
        self.assertEqual((second["a"], second["b"]), (1, 2))
        self.assertEqual(second["weight"], 1.0)
        self.assertEqual(second["direct_pairs"], 0)
        self.assertEqual(second["rm_types"],
                         ["cites", "mentions"])

    def test_counts(self):
        zoom = build()
        self.assertEqual(zoom["counts"],
                         {"nodes": 7, "communities": 3,
                          "internal_pairs": 3, "cross_pairs": 3,
                          "unassigned_nodes": 1,
                          "skipped_pairs": 1})


class PluralityTests(unittest.TestCase):
    def test_plurality_and_group_count_order(self):
        zoom = build()
        by_id = {c["id"]: c for c in zoom["communities"]}
        self.assertEqual(by_id[0]["plurality_group"], "entity")
        # group_counts are emitted in legend order, not count
        # order: source precedes entity in GROUP_ORDER.
        self.assertEqual(list(by_id[0]["group_counts"].items()),
                         [("source", 1), ("entity", 2)])
        self.assertEqual(by_id[1]["plurality_group"], "concept")
        self.assertEqual(by_id[2]["plurality_group"], "query")

    def test_tie_breaks_by_group_order(self):
        zoom = L.graph_zoom_levels(
            ["x", "y"], {"x": 0, "y": 0}, {},
            {"x": (0, 0), "y": (10, 0)},
            {"x": "entity", "y": "source"}, GROUP_ORDER,
            {"x": 1.0, "y": 1.0}, {})
        self.assertEqual(zoom["communities"][0]["plurality_group"],
                         "source")

    def test_unlisted_group_ranks_after_listed(self):
        zoom = L.graph_zoom_levels(
            ["x", "y"], {"x": 0, "y": 0}, {},
            {"x": (0, 0), "y": (10, 0)},
            {"x": "weird", "y": "query"}, GROUP_ORDER,
            {"x": 1.0, "y": 1.0}, {})
        self.assertEqual(zoom["communities"][0]["plurality_group"],
                         "query")
        self.assertEqual(list(
            zoom["communities"][0]["group_counts"]), ["query",
                                                      "weird"])


class FallbackTests(unittest.TestCase):
    def test_missing_layout_and_meta(self):
        zoom = L.graph_zoom_levels(
            ["x"], {"x": 5}, {}, {}, {"x": "entity"},
            GROUP_ORDER, {"x": 2.0}, {})
        row = zoom["communities"][0]
        self.assertIsNone(row["x"])
        self.assertIsNone(row["y"])
        self.assertEqual(row["label"], "Community 5")
        self.assertIsNone(row["hub_id"])

    def test_levels_and_rules(self):
        zoom = build()
        self.assertEqual([lv["key"] for lv in zoom["levels"]],
                         ["overview", "community", "pages"])
        for phrase in ("never re-clusters", "centroid", "median",
                       "As-of date applies at every level"):
            self.assertIn(phrase, zoom["rules"])


class DeterminismTests(unittest.TestCase):
    def test_byte_identical_regardless_of_input_order(self):
        a = json.dumps(build(), sort_keys=True)
        shuffled = dict(reversed(list(PAIRS.items())))
        b = json.dumps(build(pairs=shuffled), sort_keys=True)
        self.assertEqual(a, b)
        c = json.dumps(build(), sort_keys=True)
        self.assertEqual(a, c)


SHIPPED = (Path.home() / "workspace" / "lens-site" / "data"
           / "graph.json")


@unittest.skipUnless(SHIPPED.exists(),
                     "no shipped Lens build in this environment")
class ShippedArtefactTests(unittest.TestCase):
    """The artefact-path proof over the last real build: feeding
    the shipped graph's own nodes / partition / relation table
    back through graph_zoom_levels must partition the shipped
    node set exactly, with every page in the community the
    artefact itself assigns it."""

    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(SHIPPED.read_text(encoding="utf-8"))
        g = cls.graph
        cls.zoom = L.graph_zoom_levels(
            [n["id"] for n in g["nodes"]],
            {n["id"]: n["community"] for n in g["nodes"]},
            {(e["a"], e["b"]): {"weight": e["weight"],
                                "direct": e["direct"]}
             for e in g["edges"]},
            {n["id"]: (n["x"], n["y"]) for n in g["nodes"]},
            {n["id"]: n["group"] for n in g["nodes"]},
            [t["key"] for t in g["type_groups"]],
            {n["id"]: n["wdegree"] for n in g["nodes"]},
            {c["id"]: c for c in g["communities"]},
            {(e["a"], e["b"]): e["rm_types"]
             for e in g["edges"] if "rm_types" in e})

    def test_partitions_the_shipped_nodes_exactly(self):
        node_ids = sorted(n["id"] for n in self.graph["nodes"])
        concat = sorted(m for c in self.zoom["communities"]
                        for m in c["members"])
        self.assertEqual(concat, node_ids)
        self.assertEqual(self.zoom["counts"]["unassigned_nodes"],
                         0)
        self.assertEqual(self.zoom["counts"]["skipped_pairs"], 0)

    def test_assignment_matches_the_shipped_artefact(self):
        shipped = {n["id"]: n["community"]
                   for n in self.graph["nodes"]}
        for c in self.zoom["communities"]:
            for m in c["members"]:
                self.assertEqual(shipped[m], c["id"])
        summaries = {c["id"]: c
                     for c in self.graph["communities"]}
        for c in self.zoom["communities"]:
            self.assertEqual(c["label"],
                             summaries[c["id"]]["label"])
            self.assertEqual(c["hub_id"],
                             summaries[c["id"]]["hub_id"])
            self.assertEqual(c["member_count"],
                             len(summaries[c["id"]]["members"]))

    def test_every_shipped_pair_accounted(self):
        counts = self.zoom["counts"]
        self.assertEqual(counts["internal_pairs"]
                         + counts["cross_pairs"],
                         len(self.graph["edges"]))


if __name__ == "__main__":
    unittest.main()
