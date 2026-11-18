#!/usr/bin/env python3
"""KAG mutual indexing + logical-form retrieval (Marathon
Round 3, lane TB7, row 9).

Pins on a fixture tree: the index is MUTUAL (every page->concept
edge has its concept->page twin; check_index proves it and
catches a hand-broken index); triples carry the stated
predicates (links_to / tagged / titled / appears_on);
logical-form queries bind variables in subject and object
slots, read the index in BOTH directions, honour literals and
wildcards, and a malformed form is refused.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_kag", ROOT / "scripts" / "wiki_kag.py")
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)

ALPHA = """---
title: Alpha
tags: [agents, fixture]
---

# Alpha

Alpha rests on [[beta]] and cites [[gamma]].
"""

BETA = """---
title: Beta
tags: [agents]
---

# Beta

Beta body.
"""

GAMMA = """---
title: Gamma
---

# Gamma

Gamma body.
"""


class KagFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        (root / "wiki").mkdir(parents=True)
        (root / "wiki" / "alpha.md").write_text(ALPHA)
        (root / "wiki" / "beta.md").write_text(BETA)
        (root / "wiki" / "gamma.md").write_text(GAMMA)
        cls.index = K.build_index(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class IndexTests(KagFixture):
    def test_mutual_and_complete(self):
        self.assertEqual(K.check_index(self.index), [])
        self.assertEqual(set(self.index["pages"]),
                         {"wiki/alpha.md", "wiki/beta.md",
                          "wiki/gamma.md"})
        self.assertIn("beta", self.index["concepts"])
        self.assertEqual(self.index["concepts"]["beta"]["pages"],
                         ["wiki/alpha.md"])
        self.assertEqual(
            set(self.index["pages"]["wiki/alpha.md"]["concepts"]),
            {"beta", "gamma", "agents", "fixture"})

    def test_broken_index_is_caught(self):
        import copy
        broken = copy.deepcopy(self.index)
        broken["concepts"]["beta"]["pages"] = []
        self.assertTrue(K.check_index(broken))


class QueryTests(KagFixture):
    def test_subject_variable(self):
        hits = K.query_index(self.index, "?p links_to gamma")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["bindings"], {"p": "wiki/alpha.md"})

    def test_reverse_direction(self):
        hits = K.query_index(self.index, "beta appears_on ?p")
        self.assertEqual([h["bindings"]["p"] for h in hits],
                         ["wiki/alpha.md"])

    def test_predicate_variable_and_wildcard(self):
        hits = K.query_index(self.index, "wiki/alpha.md ?rel beta")
        self.assertTrue(any(h["bindings"].get("rel") == "links_to"
                            for h in hits))
        hits = K.query_index(self.index, "* tagged agents")
        pages = {h["triple"][0] for h in hits}
        self.assertEqual(pages, {"wiki/alpha.md", "wiki/beta.md"})

    def test_no_match_and_bad_form(self):
        self.assertEqual(K.query_index(self.index, "?p links_to zeta"),
                         [])
        with self.assertRaises(ValueError):
            K.parse_form("only two")


if __name__ == "__main__":
    unittest.main()
