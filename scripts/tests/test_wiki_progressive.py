#!/usr/bin/env python3
"""claude-mem 3-layer progressive-disclosure retrieval
(Apache-2.0 read-path design, adapted).

Pins, on a fixture corpus only:
- layer 1 is compact only (path/title/score — no summary,
  no passages) and carries its visible cost;
- layer 2 adds verbatim summaries + headings, still no
  full passages; layer 3 adds full passage texts;
- layers are cumulative and monotonic: same hits, same
  order, same scores at every layer; costs strictly grow;
- a caller stopping at layer 1 is told next_layer is 2,
  and at layer 3 that there is no next layer.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pg = _load("wiki_progressive")

DOCS = [
    (Path("wiki/concepts/irrigation.md"), """---
title: "Irrigation"
type: concept
---

# Irrigation

Irrigation waters the garden beds on a fixed schedule each week.

## Drip lines

The drip lines deliver water slowly to each irrigation bed.
"""),
    (Path("wiki/concepts/timetable.md"), """---
title: "Timetable"
type: concept
---

# Timetable

The timetable lists lessons but says nothing about watering.
"""),
]


class TestProgressive(unittest.TestCase):
    def run_layer(self, n):
        return pg.progressive_search(Path("."), "irrigation water",
                                     layer=n, docs=DOCS)

    def test_layer1_compact_only(self):
        res = self.run_layer(1)
        self.assertEqual(res["layer_reached"], 1)
        self.assertEqual(res["next_layer"], 2)
        self.assertEqual(len(res["layers"]), 1)
        hit = res["layers"][0]["hits"][0]
        self.assertEqual(set(hit), {"path", "title", "score"})
        self.assertGreater(res["layers"][0]["approx_tokens"], 0)

    def test_layer2_summaries_no_passages(self):
        res = self.run_layer(2)
        self.assertEqual(res["next_layer"], 3)
        hit = res["layers"][1]["hits"][0]
        self.assertIn("summary", hit)
        self.assertIn("Irrigation", hit["headings"])
        self.assertNotIn("passages", hit)
        # Extractive means verbatim.
        self.assertIn("waters the garden beds", hit["summary"])

    def test_layer3_full_passages(self):
        res = self.run_layer(3)
        self.assertIsNone(res["next_layer"])
        hit = res["layers"][2]["hits"][0]
        self.assertTrue(hit["passages"])
        self.assertIn("deliver water slowly",
                      hit["passages"][0]["text"])

    def test_monotonic_identity_and_cost(self):
        r1, r2, r3 = self.run_layer(1), self.run_layer(2), self.run_layer(3)
        paths = [[h["path"] for h in res["layers"][-1]["hits"]]
                 for res in (r1, r2, r3)]
        self.assertEqual(paths[0], paths[1])
        self.assertEqual(paths[1], paths[2])
        scores = [[h["score"] for h in res["layers"][-1]["hits"]]
                  for res in (r1, r2, r3)]
        self.assertEqual(scores[0], scores[2])
        costs = [res["layers"][-1]["approx_tokens"] for res in (r1, r2, r3)]
        self.assertLess(costs[0], costs[1])
        self.assertLess(costs[1], costs[2])

    def test_bad_layer_and_empty_query(self):
        with self.assertRaises(ValueError):
            pg.progressive_search(Path("."), "x", layer=9, docs=DOCS)
        res = pg.progressive_search(Path("."), "  ", layer=1, docs=DOCS)
        self.assertEqual(res["layers"], [])


if __name__ == "__main__":
    unittest.main()
