#!/usr/bin/env python3
"""Tests for the W1.8 edge provenance labels (build wave 1).

The label model lives in tools/lens/lenslib.py (edge_label /
pair_edge_label / apply_directed_pair_conflicts): every typed
edge carries a three-way provenance label (EXTRACTED /
INFERRED / AMBIGUOUS), a confidence in [0, 1] and a polarity.
These tests pin, on fixtures in temp dirs:

  - the assignment table itself: declared frontmatter and
    citations are EXTRACTED at 1.0; a verbatim "mentions"
    wikilink is EXTRACTED at 1.0; a heading-typed wikilink is
    INFERRED at 0.75; contradicts / supersedes are the
    negative-polarity types;
  - the pair aggregation the Lens bundle uses: a conflicting
    pair is AMBIGUOUS at 0.5, a derived pair is INFERRED at
    the signal confidence (capped at 0.9), a direct pair
    leans on its weakest member;
  - the traversal door's creation point: edges out of
    page_graph carry the label fields, and a directed pair
    asserting two specific types is AMBIGUOUS after the
    conflict pass (the backfill tool's rule);
  - the graph export: labels ride into the emitted edges,
    the conflict pass marks the pair AMBIGUOUS, co-citation
    edges carry a signal confidence, and a label-less door
    edge is labelled by rule (backward compatibility —
    labels are additive, absence is never an error);
  - the Lens build on a fixture repo: data/edges.jsonl rows
    and data/graph.json pair edges carry provenance /
    confidence / polarity beside the unchanged `epistemic`
    tag, and the conflicting pair renders AMBIGUOUS;
  - scripts/wiki_edge_labels.py check passes over the real
    corpus.

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
REPO = SCRIPTS.parent
sys.path.insert(0, str(REPO / "tools" / "lens"))
sys.path.insert(0, str(SCRIPTS))

import lenslib as L  # noqa: E402


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALPHA = """---
title: Alpha
type: entity
sources:
  - raw/sources/note.md
---

# Alpha

## Evidence

The case rests on [[beta]].

## Disagreements

But it clashes with [[beta]] on the remedy.
"""

BETA = """---
title: Beta
type: entity
links:
  extends:
    - wiki/entities/alpha.md
supersedes:
  - wiki/concepts/gamma.md
---

# Beta

Beta body text.
"""

GAMMA = """---
title: Gamma
type: concept
sources:
  - raw/sources/note.md
---

# Gamma

Gamma mentions [[alpha]] in passing.
"""


def write_fixture(root: Path):
    """The shared fixture corpus: alpha grounds AND
    contradicts beta (a conflicting directed pair), beta
    declares extends -> alpha (frontmatter `links:`) and
    supersedes -> gamma (a relation-vocabulary field), gamma
    mentions alpha and shares alpha's raw source (a
    co-citation pair)."""
    def mk(*parts):
        d = root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d
    mk("scripts")
    for name in ("wiki_traverse.py", "wiki_validate.py",
                 "wiki_graph_export.py"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    mk("tools", "lens")
    shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                root / "tools" / "lens" / "lenslib.py")
    (mk("wiki", "entities") / "alpha.md").write_text(
        ALPHA, encoding="utf-8")
    (mk("wiki", "entities") / "beta.md").write_text(
        BETA, encoding="utf-8")
    (mk("wiki", "concepts") / "gamma.md").write_text(
        GAMMA, encoding="utf-8")
    (mk("raw", "sources") / "note.md").write_text(
        "A fixture note.\n", encoding="utf-8")
    mk("evaluation")


class TestAssignmentTable(unittest.TestCase):
    def test_declared_and_citation_are_extracted_at_one(self):
        for kind in ("citation", "typed"):
            lab = L.edge_label(kind, "cites" if kind == "citation"
                               else "extends")
            self.assertEqual(lab["provenance"], "EXTRACTED")
            self.assertEqual(lab["confidence"], 1.0)

    def test_verbatim_mentions_is_extracted(self):
        lab = L.edge_label("wikilink", "mentions")
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("EXTRACTED", 1.0))

    def test_heading_typed_wikilink_is_inferred(self):
        lab = L.edge_label("wikilink", "grounds")
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("INFERRED", 0.75))

    def test_negative_types(self):
        for t in ("contradicts", "supersedes"):
            self.assertEqual(L.edge_polarity(t), "negative")
            self.assertEqual(
                L.edge_label("wikilink", t)["polarity"],
                "negative")
        for t in ("grounds", "extends", "exemplifies",
                  "mentions", "cites", "derives-from"):
            self.assertEqual(L.edge_polarity(t), "positive")

    def test_unknown_kind_is_inferred_at_base(self):
        lab = L.edge_label("derived", "co-cited")
        self.assertEqual(lab["provenance"], "INFERRED")
        self.assertEqual(lab["confidence"],
                         L.derived_edge_confidence())

    def test_derived_confidence_formula_and_cap(self):
        self.assertEqual(L.derived_edge_confidence(), 0.3)
        self.assertEqual(
            L.derived_edge_confidence(shared_sources=1), 0.4)
        self.assertEqual(
            L.derived_edge_confidence(common_neighbours=2), 0.4)
        self.assertEqual(
            L.derived_edge_confidence(shared_sources=99), 0.9)


class TestPairLabel(unittest.TestCase):
    def test_direct_declared_pair_is_extracted(self):
        members = [("extends", L.edge_label("typed", "extends"))]
        lab = L.pair_edge_label(members, direct=1)
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("EXTRACTED", 1.0))

    def test_direct_pair_leans_on_weakest_member(self):
        members = [("mentions", L.edge_label("wikilink",
                                             "mentions")),
                   ("grounds", L.edge_label("wikilink",
                                            "grounds"))]
        lab = L.pair_edge_label(members, direct=1)
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("INFERRED", 0.75))

    def test_conflicting_pair_is_ambiguous(self):
        members = [("grounds", L.edge_label("wikilink",
                                            "grounds")),
                   ("contradicts",
                    L.edge_label("wikilink", "contradicts"))]
        lab = L.pair_edge_label(members, direct=1)
        self.assertEqual((lab["provenance"], lab["confidence"],
                          lab["polarity"]),
                         ("AMBIGUOUS", 0.5, "mixed"))

    def test_derived_pair_is_inferred_at_signal_confidence(self):
        lab = L.pair_edge_label([], direct=0, shared_sources=2,
                                common_neighbours=1)
        self.assertEqual(lab["provenance"], "INFERRED")
        self.assertEqual(lab["confidence"],
                         L.derived_edge_confidence(
                             shared_sources=2,
                             common_neighbours=1))

    def test_same_specific_type_twice_is_not_a_conflict(self):
        members = [("grounds", L.edge_label("wikilink",
                                            "grounds")),
                   ("grounds", L.edge_label("typed", "grounds"))]
        lab = L.pair_edge_label(members, direct=1)
        self.assertEqual(lab["provenance"], "INFERRED")
        self.assertEqual(lab["confidence"], 0.75)


class TestDirectedPairConflicts(unittest.TestCase):
    def test_conflict_relabels_specific_edges_only(self):
        edges = [
            {"src": "a", "dst": "b", "relation": "grounds",
             **L.edge_label("wikilink", "grounds")},
            {"src": "a", "dst": "b", "relation": "contradicts",
             **L.edge_label("wikilink", "contradicts")},
            {"src": "a", "dst": "b", "relation": "mentions",
             **L.edge_label("wikilink", "mentions")},
            {"src": "a", "dst": "c", "relation": "grounds",
             **L.edge_label("wikilink", "grounds")},
        ]
        n = L.apply_directed_pair_conflicts(edges)
        self.assertEqual(n, 2)
        self.assertEqual(edges[0]["provenance"], "AMBIGUOUS")
        self.assertEqual(edges[0]["confidence"], 0.5)
        self.assertEqual(edges[1]["provenance"], "AMBIGUOUS")
        # mentions asserts nothing: never relabeled.
        self.assertEqual(edges[2]["provenance"], "EXTRACTED")
        # A different pair is untouched.
        self.assertEqual(edges[3]["provenance"], "INFERRED")

    def test_unlabeled_edges_pass_through(self):
        edges = [{"src": "a", "dst": "b", "relation": "grounds"},
                 {"src": "a", "dst": "b",
                  "relation": "contradicts"}]
        self.assertEqual(L.apply_directed_pair_conflicts(edges),
                         0)
        self.assertNotIn("provenance", edges[0])


class DoorFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="edge-labels-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        write_fixture(self.tmp)
        self.traverse = load_module(
            "wiki_traverse_edge_labels",
            self.tmp / "scripts" / "wiki_traverse.py")
        _pages, _keys, self.edges = self.traverse.page_graph(
            self.tmp)

    def edge(self, src, dst, relation):
        for e in self.edges:
            if (e["src"], e["dst"], e["relation"]) == \
                    (src, dst, relation):
                return e
        raise AssertionError(f"no edge {src} -> {dst} "
                             f"({relation}) in {self.edges}")

    def test_every_door_edge_is_labelled(self):
        self.assertTrue(self.edges)
        for e in self.edges:
            self.assertIn(e["provenance"],
                          L.EDGE_PROVENANCE_LABELS)
            self.assertTrue(0.0 <= e["confidence"] <= 1.0)
            self.assertIn(e["polarity"], ("positive", "negative"))

    def test_creation_point_labels(self):
        a = "wiki/entities/alpha.md"
        b = "wiki/entities/beta.md"
        g = "wiki/concepts/gamma.md"
        lab = self.edge(a, b, "grounds")
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("INFERRED", 0.75))
        lab = self.edge(a, b, "contradicts")
        self.assertEqual(lab["polarity"], "negative")
        # Frontmatter-declared edges: EXTRACTED at 1.0.
        lab = self.edge(b, a, "extends")
        self.assertEqual((lab["kind"], lab["provenance"],
                          lab["confidence"]),
                         ("typed", "EXTRACTED", 1.0))
        lab = self.edge(b, g, "supersedes")
        self.assertEqual((lab["provenance"], lab["polarity"]),
                         ("EXTRACTED", "negative"))
        # The citation edge: EXTRACTED at 1.0.
        cites = [e for e in self.edges if e["kind"] == "citation"]
        self.assertTrue(cites)
        for e in cites:
            self.assertEqual((e["provenance"], e["confidence"]),
                             ("EXTRACTED", 1.0))


class TestGraphExport(DoorFixture):
    def setUp(self):
        super().setUp()
        self.export = load_module(
            "wiki_graph_export_edge_labels",
            self.tmp / "scripts" / "wiki_graph_export.py")
        self.graph = self.export.build_graph(self.tmp)

    def test_labels_ride_into_the_export(self):
        by = {(e["source"], e["target"], e["relation"]): e
              for e in self.graph["edges"]}
        a = "wiki/entities/alpha.md"
        b = "wiki/entities/beta.md"
        # The conflicting pair: both specific edges AMBIGUOUS.
        for rel in ("grounds", "contradicts"):
            e = by[(a, b, rel)]
            self.assertEqual((e["provenance"], e["confidence"]),
                             ("AMBIGUOUS", 0.5))
        # A declared edge stays EXTRACTED at 1.0.
        e = by[(b, a, "extends")]
        self.assertEqual((e["provenance"], e["confidence"]),
                         ("EXTRACTED", 1.0))
        tally = self.graph["counts"]["edge_provenance"]
        self.assertEqual(tally.get("AMBIGUOUS"), 2)
        self.assertEqual(sum(tally.values()),
                         len(self.graph["edges"]))

    def test_inferred_edges_carry_signal_confidence(self):
        self.assertTrue(self.graph["inferred_edges"])
        for e in self.graph["inferred_edges"]:
            self.assertEqual(e["provenance"], "INFERRED")
            self.assertEqual(
                e["confidence"],
                L.derived_edge_confidence(
                    shared_sources=len(e["evidence"])))

    def test_unlabeled_door_edge_is_labelled_by_rule(self):
        # Backward compatibility: an edge dict with no label
        # fields (a door from before W1.8) gets the rule-based
        # label; with no lenslib at all, it gets None and the
        # export falls back to the standing two-way provenance.
        lens = load_module("lenslib_edge_labels_fallback",
                           self.tmp / "tools" / "lens"
                           / "lenslib.py")
        bare = {"kind": "wikilink", "relation": "grounds"}
        lab = self.export._door_edge_label(lens, bare)
        self.assertEqual((lab["provenance"], lab["confidence"]),
                         ("INFERRED", 0.75))
        self.assertIsNone(self.export._door_edge_label(None,
                                                       bare))
        carried = {"kind": "typed", "relation": "extends",
                   "provenance": "EXTRACTED", "confidence": 1.0,
                   "polarity": "positive"}
        self.assertEqual(
            self.export._door_edge_label(None, carried),
            {"provenance": "EXTRACTED", "confidence": 1.0,
             "polarity": "positive"})


class TestLensBuildFixture(unittest.TestCase):
    """The Lens build over the same fixture (links: declared
    with the no-suffix path form the Lens's route table
    resolves). Asserts the built artefacts: edges.jsonl rows
    and graph.json pair edges carry the labels beside the
    unchanged `epistemic` tag."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="edge-lens-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        root = self.tmp / "repo"
        write_fixture(root)
        # The Lens route table resolves the no-suffix path.
        beta = root / "wiki" / "entities" / "beta.md"
        beta.write_text(BETA.replace("wiki/entities/alpha.md",
                                     "wiki/entities/alpha"),
                        encoding="utf-8")
        shutil.copy(SCRIPTS / "wiki_search.py",
                    root / "scripts" / "wiki_search.py")
        subprocess.run(["git", "init", "-q", "."],
                       cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t",
                        "-c", "user.name=t", "commit", "-qm",
                        "fixture"], cwd=root, check=True)
        self.out = self.tmp / "out"
        subprocess.run(
            [sys.executable,
             str(REPO / "tools" / "lens" / "build_lens.py"),
             "--repo", str(root), "--out", str(self.out)],
            check=True, capture_output=True, text=True)

    def test_edge_table_rows_carry_labels(self):
        rows = [json.loads(line) for line in
                (self.out / "data" / "edges.jsonl")
                .read_text(encoding="utf-8").splitlines() if line]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["epistemic"], "extracted")
            self.assertIn(r["provenance"],
                          L.EDGE_PROVENANCE_LABELS)
            self.assertTrue(0.0 <= r["confidence"] <= 1.0)
        by = {(r["src"], r["dst"], r["type"]): r for r in rows}
        self.assertEqual(
            (by[("alpha", "beta", "grounds")]["provenance"],
             by[("alpha", "beta", "grounds")]["confidence"]),
            ("INFERRED", 0.75))
        self.assertEqual(
            by[("beta", "alpha", "extends")]["provenance"],
            "EXTRACTED")
        cites = [r for r in rows if r["kind"] == "citation"]
        self.assertTrue(cites)
        self.assertTrue(all(r["provenance"] == "EXTRACTED"
                            and r["confidence"] == 1.0
                            for r in cites))

    def test_graph_pairs_carry_labels(self):
        graph = json.loads((self.out / "data" / "graph.json")
                           .read_text(encoding="utf-8"))
        self.assertTrue(graph["edges"])
        for e in graph["edges"]:
            self.assertIn(e["epistemic"],
                          ("extracted", "inferred"))
            self.assertIn(e["provenance"],
                          L.EDGE_PROVENANCE_LABELS)
            self.assertTrue(0.0 <= e["confidence"] <= 1.0)
            self.assertIn(e["polarity"],
                          ("positive", "negative", "mixed"))
        pair = {(e["a"], e["b"]): e for e in graph["edges"]}
        ab = pair[("alpha", "beta")]
        self.assertEqual((ab["provenance"], ab["confidence"],
                          ab["polarity"]),
                         ("AMBIGUOUS", 0.5, "mixed"))
        self.assertEqual(ab["epistemic"], "extracted")


class TestBackfillTool(unittest.TestCase):
    def test_check_over_the_real_corpus(self):
        tool = load_module("wiki_edge_labels_tool",
                           SCRIPTS / "wiki_edge_labels.py")
        report = tool.build_report(REPO)
        self.assertGreater(report["counts"]["edges"], 0)
        for e in report["edges"]:
            self.assertIn(e["provenance"],
                          L.EDGE_PROVENANCE_LABELS)
            self.assertIn(e["rule"], tool.RULES)
        self.assertEqual(
            sum(report["counts"]["by_provenance"].values()),
            report["counts"]["edges"])


if __name__ == "__main__":
    unittest.main()
