#!/usr/bin/env python3
"""the build: graph analytics for the Lens — typed link edges,
co-citation, label-propagation communities, link prediction.

The pure functions live in tools/lens/lenslib.py: infer_link_type
(the heading -> link-type mapping), extract_wikilinks_typed
(section-aware link extraction), extract_link_sentences,
cocitation_index, label_propagation, link_suggestions
(Adamic-Adar). All deterministic: sorted iteration, fixed
tie-breaks, no randomness — the tests pin exact values.

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


class TestInferLinkType(unittest.TestCase):
    def test_closed_vocabulary(self):
        for heading in ("Contradictions", "Evidence", "Examples",
                        "Extensions", "What superseded it",
                        "Connections", None, ""):
            self.assertIn(L.infer_link_type(heading), L.LINK_TYPES)

    def test_contradiction_headings(self):
        self.assertEqual(L.infer_link_type("Contradictions"),
                         "contradicts")
        self.assertEqual(
            L.infer_link_type("Open questions / contradictions"),
            "contradicts")
        self.assertEqual(L.infer_link_type("Lane 1 — Contradictions"),
                         "contradicts")
        self.assertEqual(L.infer_link_type("Conflicts and disputes"),
                         "contradicts")

    def test_grounding_headings(self):
        self.assertEqual(L.infer_link_type("Sources used"), "grounds")
        self.assertEqual(L.infer_link_type("Evidence"), "grounds")
        self.assertEqual(L.infer_link_type("Citations and provenance"),
                         "grounds")

    def test_priority_contradiction_beats_grounding(self):
        # "evidence" is a grounds keyword, but a heading that names
        # a contradiction is the more specific signal and wins.
        self.assertEqual(
            L.infer_link_type("Contradictions in the evidence base"),
            "contradicts")

    def test_other_types(self):
        self.assertEqual(L.infer_link_type("Examples"), "exemplifies")
        self.assertEqual(L.infer_link_type("Case study: the build"),
                         "exemplifies")
        self.assertEqual(L.infer_link_type("What superseded it"),
                         "supersedes")
        self.assertEqual(L.infer_link_type("Deprecated routes"),
                         "supersedes")
        self.assertEqual(L.infer_link_type("Extensions"), "extends")
        self.assertEqual(L.infer_link_type("Follow-up work"), "extends")

    def test_default_is_mentions(self):
        self.assertEqual(L.infer_link_type("Connections"), "mentions")
        self.assertEqual(L.infer_link_type("Status"), "mentions")
        self.assertEqual(L.infer_link_type("Summary"), "mentions")
        self.assertEqual(L.infer_link_type(None), "mentions")
        self.assertEqual(L.infer_link_type(""), "mentions")


class TestExtractWikilinksTyped(unittest.TestCase):
    BODY = """Links [[alpha]] and [[beta|Beta]] up top.

## Evidence

Grounded [[gamma]] here.

```markdown
## Contradictions
[[fake]] inside a fence
```

## Contradictions

Against [[delta]] and a `[[code-span]]` non-link.
"""

    def test_types_and_sections(self):
        links = L.extract_wikilinks_typed(self.BODY)
        by_target = {t: (h, ty) for t, _a, _l, h, ty in links}
        self.assertEqual(by_target["alpha"], (None, "mentions"))
        self.assertEqual(by_target["beta"], (None, "mentions"))
        self.assertEqual(by_target["gamma"], ("Evidence", "grounds"))
        self.assertEqual(by_target["delta"],
                         ("Contradictions", "contradicts"))

    def test_code_never_yields_links(self):
        targets = [t for t, *_ in L.extract_wikilinks_typed(self.BODY)]
        self.assertNotIn("fake", targets)
        self.assertNotIn("code-span", targets)

    def test_same_link_set_as_plain_extraction(self):
        typed = sorted(t for t, *_ in L.extract_wikilinks_typed(self.BODY))
        plain = sorted(t for t, _a, _l in L.extract_wikilinks(self.BODY))
        self.assertEqual(typed, plain)

    def test_heading_link_typed_by_its_own_heading(self):
        body = "## See [[alpha]] for details\n\nBody [[beta]].\n"
        links = L.extract_wikilinks_typed(body)
        by_target = {t: (h, ty) for t, _a, _l, h, ty in links}
        self.assertEqual(by_target["alpha"][0], "See [[alpha]] for details")
        self.assertEqual(by_target["beta"][0], "See [[alpha]] for details")


class TestExtractLinkSentences(unittest.TestCase):
    BODY = """Alpha cites [[beta]] and [[gamma]] together in one sentence. A second sentence names [[delta]] alone.

## A heading naming [[beta]]

| [[beta]] | [[gamma]] |
| --- | --- |

> A quoted line links [[epsilon]] here.
"""

    def test_sentence_pairs(self):
        sents = L.extract_link_sentences(self.BODY)
        target_sets = [sorted(ts) for _text, ts in sents]
        self.assertIn(["beta", "gamma"], target_sets)
        self.assertIn(["delta"], target_sets)
        self.assertIn(["epsilon"], target_sets)

    def test_headings_and_tables_are_not_sentences(self):
        sents = L.extract_link_sentences(self.BODY)
        # The heading line and the table row each name beta (and
        # gamma) but must never appear as citing sentences.
        texts = [text for text, _ts in sents]
        self.assertEqual(len(texts), 3)
        self.assertTrue(all("heading naming" not in t for t in texts))

    def test_display_text_uses_labels(self):
        sents = L.extract_link_sentences(self.BODY)
        first = sents[0][0]
        self.assertIn("beta", first)
        self.assertNotIn("[[", first)


class TestLabelPropagation(unittest.TestCase):
    def weights(self):
        w = {}
        for a, b in [("a", "b"), ("a", "c"), ("b", "c"),
                     ("d", "e"), ("d", "f"), ("e", "f")]:
            w[(a, b)] = 1.0
        w[("c", "d")] = 0.1  # one weak bridge
        return w

    def test_two_triangles_stay_apart(self):
        comm = L.label_propagation(
            ["a", "b", "c", "d", "e", "f", "g"], self.weights())
        self.assertEqual(comm["a"], comm["b"])
        self.assertEqual(comm["b"], comm["c"])
        self.assertEqual(comm["d"], comm["e"])
        self.assertEqual(comm["e"], comm["f"])
        self.assertNotEqual(comm["a"], comm["d"])

    def test_isolated_node_is_its_own_community(self):
        comm = L.label_propagation(
            ["a", "b", "c", "d", "e", "f", "g"], self.weights())
        self.assertNotIn(comm["g"], (comm["a"], comm["d"]))

    def test_keywords_match_at_word_starts_only(self):
        # The substring traps: stems must not fire inside words.
        self.assertEqual(L.infer_link_type("Extensions"), "extends")
        self.assertEqual(L.infer_link_type("Resources"), "mentions")
        self.assertEqual(L.infer_link_type("Background"), "mentions")
        self.assertEqual(L.infer_link_type("Tensions"), "contradicts")

    def test_renumbered_by_smallest_member(self):
        comm = L.label_propagation(
            ["a", "b", "c", "d", "e", "f", "g"], self.weights())
        self.assertEqual(comm["a"], 0)  # 'a' is the smallest member
        self.assertEqual(sorted(set(comm.values())), [0, 1, 2])

    def test_deterministic(self):
        nodes = ["g", "f", "e", "d", "c", "b", "a"]  # unsorted input
        self.assertEqual(L.label_propagation(nodes, self.weights()),
                         L.label_propagation(nodes, self.weights()))

    def test_no_edges_each_node_alone(self):
        comm = L.label_propagation(["x", "y"], {})
        self.assertNotEqual(comm["x"], comm["y"])


class TestLinkSuggestions(unittest.TestCase):
    # a and b share neighbours w (degree 2) and z (degree 3);
    # w and z share neighbours a and b (both degree 2).
    NB = {"a": {"w", "z"}, "b": {"w", "z"}, "w": {"a", "b"},
          "z": {"a", "b", "x"}, "x": {"z"}}

    def test_adamic_adar_values_and_order(self):
        out = L.link_suggestions(self.NB)
        self.assertEqual([(e["a"], e["b"]) for e in out],
                         [("w", "z"), ("a", "b"), ("a", "x"), ("b", "x")])
        by_pair = {(e["a"], e["b"]): e for e in out}
        self.assertAlmostEqual(by_pair[("w", "z")]["adamic_adar"],
                               round(2 / math.log(2), 4))
        self.assertAlmostEqual(
            by_pair[("a", "b")]["adamic_adar"],
            round(1 / math.log(2) + 1 / math.log(3), 4))
        self.assertEqual(by_pair[("a", "b")]["common_neighbours"], 2)
        self.assertEqual(by_pair[("a", "b")]["shared_neighbours"],
                         ["w", "z"])

    def test_adjacent_pairs_never_suggested(self):
        for e in L.link_suggestions(self.NB):
            self.assertNotIn(e["b"], self.NB[e["a"]])
            self.assertLess(e["a"], e["b"])

    def test_top_n_cap(self):
        self.assertEqual(len(L.link_suggestions(self.NB, top_n=2)), 2)


class TestCocitationIndex(unittest.TestCase):
    CITERS = {"alpha": {"p1", "p2"}, "beta": {"p1", "p2", "p3"},
              "gamma": {"p3"}}
    PAIRS = [("p1", "alpha", "beta", "Alpha and Beta together."),
             ("p2", "beta", "alpha", "Beta with Alpha again.")]

    def test_structure_and_symmetry(self):
        idx = L.cocitation_index(self.CITERS, self.PAIRS)
        alpha = idx["alpha"]
        self.assertEqual(len(alpha), 1)
        self.assertEqual(alpha[0]["other"], "beta")
        self.assertEqual(alpha[0]["shared_citers"], 2)
        self.assertEqual(alpha[0]["citers"], ["p1", "p2"])
        self.assertEqual(len(alpha[0]["sentences"]), 2)
        beta = idx["beta"]
        self.assertEqual([e["other"] for e in beta], ["alpha", "gamma"])
        self.assertEqual(beta[1]["shared_citers"], 1)
        self.assertEqual(beta[1]["sentences"], [])
        self.assertEqual(idx["gamma"][0]["other"], "beta")

    def test_no_shared_citer_no_entry(self):
        idx = L.cocitation_index(self.CITERS, self.PAIRS)
        self.assertNotIn("gamma",
                         [e["other"] for e in idx.get("alpha", [])])

    def test_caps(self):
        idx = L.cocitation_index(self.CITERS, self.PAIRS, max_others=1)
        self.assertTrue(all(len(v) <= 1 for v in idx.values()))


if __name__ == "__main__":
    unittest.main()
