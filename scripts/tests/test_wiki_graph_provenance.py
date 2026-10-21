#!/usr/bin/env python3
"""Tests for the Graphify edge-provenance addition to
scripts/wiki_graph_export.py (Marathon R3, Lane TA5).

Pins, on a FIXTURE corpus in a temp dir (real scripts copied
in, as in test_wiki_graph_export.py):
  - every main-census edge carries provenance "EXTRACTED"
    (wikilink / typed edges are physically in a page);
  - edge_provenance classifies door kinds: wikilink, typed
    and citation are EXTRACTED; anything else is INFERRED;
  - INFERRED co-cited edges: two pages citing the same raw
    source in frontmatter `sources:` get one inferred edge
    with the shared source as evidence; a page citing a
    unique source gets none; inferred edges never enter the
    main `edges` list, degrees or the `edges` count;
  - counts carry extracted_edges / inferred_edges;
  - the rendered HTML distinguishes them: the dashed-teal
    inferred drawing code and the legend text are present,
    and the embedded JSON round-trips the inferred edges.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent

PAGE_A = """---
title: Fable Alpha
type: entity
sources:
  - raw/sources/shared-note.md
---

# Fable Alpha

See [[beta]].
"""
PAGE_B = """---
title: Fable Beta
type: concept
sources:
  - raw/sources/shared-note.md
  - raw/sources/beta-only.md
---

# Fable Beta
"""
PAGE_C = """---
title: Fable Gamma
type: entity
sources:
  - raw/sources/gamma-only.md
---

# Fable Gamma
"""


def load_module(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_graph_export_prov", root / "scripts" / "wiki_graph_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGraphProvenance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="graph-prov-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_graph_export.py", "wiki_traverse.py",
                     "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        lens = self.tmp / "tools" / "lens"
        lens.mkdir(parents=True)
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    lens / "lenslib.py")
        (self.tmp / "wiki" / "entities").mkdir(parents=True)
        (self.tmp / "wiki" / "concepts").mkdir(parents=True)
        (self.tmp / "wiki" / "entities" / "alpha.md").write_text(
            PAGE_A, encoding="utf-8")
        (self.tmp / "wiki" / "concepts" / "beta.md").write_text(
            PAGE_B, encoding="utf-8")
        (self.tmp / "wiki" / "entities" / "gamma.md").write_text(
            PAGE_C, encoding="utf-8")
        self.mod = load_module(self.tmp)
        self.graph = self.mod.build_graph(self.tmp)

    def test_extracted_edges_carry_provenance(self):
        self.assertTrue(self.graph["edges"])
        for e in self.graph["edges"]:
            self.assertEqual(e["provenance"], "EXTRACTED")

    def test_provenance_classifier(self):
        for kind in ("wikilink", "typed", "citation"):
            self.assertEqual(
                self.mod.edge_provenance({"kind": kind}), "EXTRACTED")
        self.assertEqual(
            self.mod.edge_provenance({"kind": "inferred"}), "INFERRED")
        self.assertEqual(self.mod.edge_provenance({}), "INFERRED")

    def test_inferred_co_cited_edge(self):
        inf = self.graph["inferred_edges"]
        self.assertEqual(len(inf), 1)
        e = inf[0]
        self.assertEqual(e["provenance"], "INFERRED")
        self.assertEqual(e["relation"], "co-cited")
        self.assertEqual({e["source"], e["target"]},
                         {"wiki/entities/alpha.md",
                          "wiki/concepts/beta.md"})
        self.assertEqual(e["evidence"], ["raw/sources/shared-note.md"])

    def test_inferred_never_in_main_census(self):
        self.assertEqual(self.graph["counts"]["inferred_edges"], 1)
        self.assertEqual(self.graph["counts"]["extracted_edges"],
                         self.graph["counts"]["edges"])
        self.assertFalse(any(e["kind"] == "inferred"
                             for e in self.graph["edges"]))
        # Gamma is an orphan in the extracted graph despite the
        # export deriving edges elsewhere.
        gamma = [n for n in self.graph["nodes"]
                 if n["id"] == "wiki/entities/gamma.md"][0]
        self.assertEqual((gamma["out_degree"], gamma["in_degree"]), (0, 0))

    def test_html_renders_the_distinction(self):
        html = self.mod.render_html(self.graph)
        self.assertIn("INFERRED edge (co-cited", html)
        self.assertIn("setLineDash([5, 4])", html)
        self.assertIn("inferredEdges", html)
        m = re.search(
            r'<script id="graph-data" type="application/json">'
            r"(.*?)</script>", html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["inferred_edges"]), 1)
        self.assertEqual(data["inferred_edges"][0]["provenance"],
                         "INFERRED")


if __name__ == "__main__":
    unittest.main()
