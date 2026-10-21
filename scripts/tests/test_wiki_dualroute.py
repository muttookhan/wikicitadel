#!/usr/bin/env python3
"""CN5b dual-level retrieval routing (LightRAG dual-level idea,
MIT, adapted).

Pins, on fixtures only:
- the deterministic routing rules R1-R8 on stated query shapes;
- passage splitting by heading with line ranges;
- passage ranking finds the chunk carrying the queried fact,
  not merely the page;
- search() honours the route (page route returns no passages,
  passage route returns no page hits, both returns both).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dr = _load("wiki_dualroute")

PAGE_A = """---
title: "Irrigation"
type: concept
---

# Irrigation

Irrigation is the practice of watering crops on a schedule.

## Drip lines

The drip lines were installed in 2019 and deliver two litres
per hour to each bed through small emitters.
"""
PAGE_B = """---
title: "Timetable"
type: concept
---

# Timetable

The timetable sets the weekly rhythm of lessons and breaks.
"""


class TestRoutingRules(unittest.TestCase):
    def check(self, query, route, rule):
        d = dr.classify_query(query)
        self.assertEqual((d["route"], d["rule"]), (route, rule), query)

    def test_rules(self):
        self.check("page: irrigation", "page", "R1")
        self.check("chunk: drip emitters", "passage", "R1")
        self.check('"drip lines were installed"', "passage", "R2")
        self.check("drip lines installed 2019", "passage", "R3")
        self.check("overview of irrigation themes", "page", "R4")
        self.check("what is irrigation", "page", "R5")
        self.check("irrigation", "page", "R5")
        self.check("where are the emitters mentioned in the text",
                   "passage", "R6")
        self.check("how much water do the drip emitters deliver "
                   "to each bed every hour", "passage", "R7")
        # 4-6 terms, no cue at all: ambiguous -> both.
        self.check("alpha beta gamma delta", "both", "R8")

    def test_prefix_is_stripped(self):
        d = dr.classify_query("passage: drip lines")
        self.assertEqual(d["query"], "drip lines")
        self.assertIn("drip", d["terms"])


class TestPassages(unittest.TestCase):
    def test_split_by_heading_with_lines(self):
        parts = dr.split_passages(PAGE_A, "wiki/concepts/irrigation.md")
        heads = [p["heading"] for p in parts]
        self.assertIn("Drip lines", heads)
        drip = next(p for p in parts if p["heading"] == "Drip lines")
        self.assertLess(drip["start_line"], drip["end_line"])
        self.assertIn("two litres", drip["text"])

    def test_rank_passages_finds_fact_chunk(self):
        docs = [(Path("wiki/a.md"), PAGE_A), (Path("wiki/b.md"), PAGE_B)]
        hits = dr.rank_passages(["drip", "emitters"], docs)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["heading"], "Drip lines")

    def test_search_honours_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki" / "concepts").mkdir(parents=True)
            (root / "wiki" / "concepts" / "irrigation.md").write_text(
                PAGE_A, encoding="utf-8")
            (root / "wiki" / "concepts" / "timetable.md").write_text(
                PAGE_B, encoding="utf-8")
            page_res = dr.search(root, "what is irrigation")
            self.assertEqual(page_res["route"], "page")
            self.assertTrue(page_res["pages"])
            self.assertEqual(page_res["passages"], [])
            pass_res = dr.search(root, "drip lines installed 2019")
            self.assertEqual(pass_res["route"], "passage")
            self.assertEqual(pass_res["pages"], [])
            self.assertTrue(pass_res["passages"])
            self.assertIn("Drip lines", pass_res["passages"][0]["heading"])


if __name__ == "__main__":
    unittest.main()
