#!/usr/bin/env python3
"""Tests for scripts/wiki_graph_export.py (15-gap item 5:
the standalone interactive graph HTML export).

Pins, on a FIXTURE corpus in a temp dir (the real scripts
copied in, so the fixture root resolves exactly as the real
repo does for the traversal door this tool delegates to):

  - node extraction: every page is a node — orphans,
    tombstones and severed pages included — with title /
    type / stage taken from frontmatter where provided;
  - edge extraction: the door's page-to-page edges only
    (wikilink edges typed by their heading, frontmatter
    `links:` and relation-field typed edges), with citation
    edges to raw/ excluded because their targets are not
    pages; out/in degrees follow from the emitted edges;
  - standing marks: `status: tombstoned` marks a node
    tombstoned; a PAGE-level severance entry marks a node
    severed, while a claim-level entry naming a page sets
    has_severed_claim only — the page is not itself severed;
  - the emitted HTML: the embedded JSON data block parses
    back to the built graph; there are NO external asset
    references at all (no http:// or https:// anywhere in
    the file, no <link>, no external <script src>, no
    @import); the search / focus / neighbour-highlight /
    seeded-layout / details-pane JavaScript is present;
  - determinism: two CLI runs over the same fixture emit
    byte-identical files;
  - analytics (Marathon R2 Lane G): deterministic label-
    propagation communities (input order must not matter),
    god nodes ranked by degree with in/out shown, node tags
    from frontmatter, and the communities / god-nodes
    panels plus the type/tag filter controls in the HTML.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
TOOL = "wiki_graph_export.py"

ALPHA = """---
title: Alpha
type: entity
stage: seedling
status: active
tags: [graph, fixture]
sources:
  - raw/sources/open-note.md
---

# Alpha

## Evidence

The case rests on [[beta]].

## Disagreements

See [[gamma]] for the other side.
"""

BETA = """---
title: Beta
type: concept
stage: budding
tags:
  - graph
  - hub
links:
  extends:
    - wiki/entities/alpha.md
supersedes:
  - wiki/entities/gamma.md
---

# Beta

Beta body text about graphs.
"""

GAMMA = """---
title: Gamma
type: entity
tags: [fixture]
---

# Gamma

Gamma links back to [[alpha]].
"""

RETIRED = """---
title: Retired
type: concept
status: tombstoned
tombstoned: 2026-10-20
tombstone_reason: "Superseded by Alpha in the fixture."
replaced_by: wiki/entities/alpha.md
---

# Retired

> [!warning] Tombstone — this page was retired on 2026-10-20

Its replacement is [[alpha]].
"""

SEVERED_NOTE = """---
title: Severed Note
type: source
---

# Severed Note

This page links to [[alpha]] but its own cues are cut.
"""

LONELY = """---
title: Lonely
type: query
---

# Lonely

No links in, no links out.
"""

SEVERANCE = {
    "kind": "retrieval-severance",
    "version": 1,
    "entries": [
        {"id": "sev-0001", "kind": "page",
         "page": "wiki/sources/severed-note.md", "claim": None,
         "cues": {"phrases": [], "terms": ["severed"]},
         "source": {"register": "wiki/ frontmatter",
                    "line": None, "record_id": "fixture",
                    "signal": "status: superseded"}},
        {"id": "sev-0002", "kind": "treatment",
         "page": "wiki/entities/alpha.md",
         "claim": "a severed claim Alpha carries",
         "cues": {"phrases": [], "terms": ["severed"]},
         "source": {"register": "evaluation/treatment-register.jsonl",
                    "line": 1, "record_id": "treat-0001",
                    "signal": "negative treatment (standing grade)"}},
    ],
}

# The fixture's page-to-page edges, as (source, target, relation):
EXPECTED_EDGES = {
    ("wiki/entities/alpha.md", "wiki/concepts/beta.md", "grounds"),
    ("wiki/entities/alpha.md", "wiki/entities/gamma.md", "contradicts"),
    ("wiki/concepts/beta.md", "wiki/entities/alpha.md", "extends"),
    ("wiki/concepts/beta.md", "wiki/entities/gamma.md", "supersedes"),
    ("wiki/entities/gamma.md", "wiki/entities/alpha.md", "mentions"),
    # The tombstone's replacement link sits under its "# Retired"
    # heading, and the shared SECTION_TYPE_RULES type a link under
    # a "retired" heading as supersedes — the door's typing, kept.
    ("wiki/concepts/retired.md", "wiki/entities/alpha.md", "supersedes"),
    ("wiki/sources/severed-note.md", "wiki/entities/alpha.md", "mentions"),
}
EXPECTED_IDS = {
    "wiki/entities/alpha.md", "wiki/concepts/beta.md",
    "wiki/entities/gamma.md", "wiki/concepts/retired.md",
    "wiki/sources/severed-note.md", "wiki/queries/lonely.md",
}


def load_export_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "wiki_graph_export_fixture", root / "scripts" / TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_data(html_text: str):
    m = re.search(
        r'<script id="graph-data" type="application/json">(.*?)</script>',
        html_text, re.S)
    if not m:
        raise AssertionError("no embedded graph-data block in the HTML")
    return json.loads(m.group(1))


class GraphFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="graph-export-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self._mk("scripts")
        for name in (TOOL, "wiki_traverse.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        lens = self._mk("tools", "lens")
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    lens / "lenslib.py")
        (self._mk("wiki", "entities") / "alpha.md").write_text(
            ALPHA, encoding="utf-8")
        (self._mk("wiki", "entities") / "gamma.md").write_text(
            GAMMA, encoding="utf-8")
        (self._mk("wiki", "concepts") / "beta.md").write_text(
            BETA, encoding="utf-8")
        (self._mk("wiki", "concepts") / "retired.md").write_text(
            RETIRED, encoding="utf-8")
        (self._mk("wiki", "sources") / "severed-note.md").write_text(
            SEVERED_NOTE, encoding="utf-8")
        (self._mk("wiki", "queries") / "lonely.md").write_text(
            LONELY, encoding="utf-8")
        ev = self._mk("evaluation")
        (ev / "retrieval-severance.json").write_text(
            json.dumps(SEVERANCE), encoding="utf-8")
        self.mod = load_export_module(self.tmp)
        self.graph = self.mod.build_graph(self.tmp)

    def _mk(self, *parts):
        d = self.tmp.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def node(self, rel):
        for n in self.graph["nodes"]:
            if n["id"] == rel:
                return n
        self.fail(f"no node for {rel}")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             "--root", str(self.tmp), *args],
            capture_output=True, text=True)


class TestExtraction(GraphFixture):
    def test_all_pages_are_nodes(self):
        self.assertEqual({n["id"] for n in self.graph["nodes"]},
                         EXPECTED_IDS)
        self.assertEqual(self.graph["counts"]["pages"], 6)

    def test_node_fields_from_frontmatter(self):
        alpha = self.node("wiki/entities/alpha.md")
        self.assertEqual(alpha["title"], "Alpha")
        self.assertEqual(alpha["type"], "entity")
        self.assertEqual(alpha["stage"], "seedling")
        self.assertEqual(alpha["status"], "active")
        beta = self.node("wiki/concepts/beta.md")
        self.assertEqual(beta["type"], "concept")
        self.assertEqual(beta["stage"], "budding")
        gamma = self.node("wiki/entities/gamma.md")
        self.assertEqual(gamma["title"], "Gamma")
        self.assertIsNone(gamma["stage"])  # absent, never invented

    def test_edges_are_the_page_graph_only(self):
        got = {(e["source"], e["target"], e["relation"])
               for e in self.graph["edges"]}
        self.assertEqual(got, EXPECTED_EDGES)
        self.assertEqual(self.graph["counts"]["edges"],
                         len(EXPECTED_EDGES))
        for e in self.graph["edges"]:
            self.assertIn(e["source"], EXPECTED_IDS)
            self.assertIn(e["target"], EXPECTED_IDS)
            self.assertIn(e["kind"], ("wikilink", "typed"))
        # Alpha's `sources:` citation points at a raw file:
        # no node, no edge may carry it.
        self.assertFalse(any("raw" in e["target"]
                             for e in self.graph["edges"]))

    def test_degrees_follow_the_edges(self):
        alpha = self.node("wiki/entities/alpha.md")
        self.assertEqual(alpha["out_degree"], 2)
        self.assertEqual(alpha["in_degree"], 4)
        beta = self.node("wiki/concepts/beta.md")
        self.assertEqual((beta["out_degree"], beta["in_degree"]), (2, 1))
        gamma = self.node("wiki/entities/gamma.md")
        self.assertEqual((gamma["out_degree"], gamma["in_degree"]), (1, 2))
        lonely = self.node("wiki/queries/lonely.md")
        self.assertEqual((lonely["out_degree"], lonely["in_degree"]), (0, 0))
        self.assertEqual(self.graph["counts"]["orphans"], 1)


class TestMarking(GraphFixture):
    def test_tombstoned_node_is_marked_and_kept(self):
        retired = self.node("wiki/concepts/retired.md")
        self.assertTrue(retired["tombstoned"])
        self.assertFalse(retired["severed"])
        self.assertEqual(self.graph["counts"]["tombstoned"], 1)

    def test_severed_page_is_marked(self):
        sev = self.node("wiki/sources/severed-note.md")
        self.assertTrue(sev["severed"])
        self.assertFalse(sev["tombstoned"])
        self.assertEqual(self.graph["counts"]["severed"], 1)

    def test_claim_level_entry_does_not_sever_the_page(self):
        alpha = self.node("wiki/entities/alpha.md")
        self.assertFalse(alpha["severed"])
        self.assertTrue(alpha["has_severed_claim"])
        self.assertFalse(
            self.node("wiki/concepts/beta.md")["has_severed_claim"])

    def test_marks_survive_into_the_html(self):
        html = self.mod.render_html(self.graph)
        data = extract_data(html)
        by_id = {n["id"]: n for n in data["nodes"]}
        self.assertTrue(by_id["wiki/concepts/retired.md"]["tombstoned"])
        self.assertTrue(by_id["wiki/sources/severed-note.md"]["severed"])
        # The drawing code branches on both marks.
        self.assertIn("node.tombstoned", html)
        self.assertIn("node.severed", html)
        self.assertIn("TOMBSTONED", html)
        self.assertIn("SEVERED", html)


class TestHtml(GraphFixture):
    def test_embedded_data_round_trips(self):
        html = self.mod.render_html(self.graph)
        self.assertEqual(extract_data(html), self.graph)

    def test_no_external_assets(self):
        html = self.mod.render_html(self.graph)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("@import", html)
        self.assertIsNone(re.search(r"<script[^>]+\bsrc=", html))
        self.assertIsNone(re.search(r"<img[^>]+\bsrc=", html))

    def test_interactivity_is_present(self):
        html = self.mod.render_html(self.graph)
        # Search box + focus-by-title.
        self.assertIn('id="search"', html)
        self.assertIn("searchByTitle", html)
        self.assertIn("focusNode", html)
        # Click-to-highlight neighbours.
        self.assertIn("highlightNeighbours", html)
        self.assertIn("neighboursOf", html)
        # Deterministic seeded layout, computed in JS.
        self.assertIn("LAYOUT_SEED", html)
        self.assertIn("mulberry32", html)
        self.assertIn("computeLayout", html)
        # Pan / zoom handlers.
        self.assertIn("pointerdown", html)
        self.assertIn("wheel", html)
        # Colour by page type.
        self.assertIn("TYPE_COLORS", html)
        self.assertIn("colorForType", html)
        # Details pane with degrees + neighbour list.
        self.assertIn('id="details"', html)
        self.assertIn("showDetails", html)
        self.assertIn("Out-degree", html)
        self.assertIn("In-degree", html)
        self.assertIn("Neighbours", html)

    def test_cli_writes_default_and_explicit_outs(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        default_out = self.tmp / "evaluation" / "graph.html"
        self.assertTrue(default_out.is_file())
        self.assertIn("6 pages", r.stdout)
        explicit = self.tmp / "elsewhere" / "g.html"
        r = self.run_cli("--out", str(explicit))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(explicit.is_file())
        data = extract_data(explicit.read_text(encoding="utf-8"))
        self.assertEqual({n["id"] for n in data["nodes"]}, EXPECTED_IDS)

    def test_two_runs_are_byte_identical(self):
        a = self.tmp / "a.html"
        b = self.tmp / "b.html"
        for out in (a, b):
            r = self.run_cli("--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        # And the pure render path agrees with itself too.
        self.assertEqual(self.mod.render_html(self.graph),
                         self.mod.render_html(self.graph))


class TestAnalytics(GraphFixture):
    """Marathon R2 Lane G: communities, god nodes, tags."""

    def test_tags_ride_on_nodes_sorted(self):
        self.assertEqual(self.node("wiki/entities/alpha.md")["tags"],
                         ["fixture", "graph"])
        self.assertEqual(self.node("wiki/concepts/beta.md")["tags"],
                         ["graph", "hub"])
        self.assertEqual(self.node("wiki/entities/gamma.md")["tags"],
                         ["fixture"])
        self.assertEqual(self.node("wiki/queries/lonely.md")["tags"], [])

    def test_communities_partition_the_fixture(self):
        comms = self.graph["communities"]
        self.assertEqual(self.graph["counts"]["communities"], 2)
        self.assertEqual([c["size"] for c in comms], [5, 1])
        big, solo = comms
        self.assertEqual(big["id"], "C1")
        self.assertEqual(set(big["members"]), EXPECTED_IDS
                         - {"wiki/queries/lonely.md"})
        self.assertEqual(big["members"], sorted(big["members"]))
        self.assertIn(big["label"], big["members"])
        self.assertEqual(solo["id"], "C2")
        self.assertEqual(solo["members"], ["wiki/queries/lonely.md"])
        # Every node records the community it was assigned to.
        for n in self.graph["nodes"]:
            expect = "C2" if n["id"] == "wiki/queries/lonely.md" else "C1"
            self.assertEqual(n["community"], expect)
        # Top pages are the community's highest-degree members.
        self.assertEqual(big["top_pages"][0]["id"],
                         "wiki/entities/alpha.md")
        self.assertEqual(big["top_pages"][0]["degree"], 6)

    def test_community_detection_is_deterministic(self):
        a1, c1 = self.mod.compute_communities(
            self.graph["nodes"], self.graph["edges"])
        a2, c2 = self.mod.compute_communities(
            self.graph["nodes"], self.graph["edges"])
        self.assertEqual((a1, c1), (a2, c2))
        # Input order must not matter: reversed inputs, same result.
        a3, c3 = self.mod.compute_communities(
            list(reversed(self.graph["nodes"])),
            list(reversed(self.graph["edges"])))
        self.assertEqual((a1, c1), (a3, c3))
        # And a full rebuild agrees byte-for-byte on the analytics.
        again = self.mod.build_graph(self.tmp)
        self.assertEqual(again["communities"], self.graph["communities"])
        self.assertEqual(again["god_nodes"], self.graph["god_nodes"])

    def test_god_nodes_rank_the_fixture(self):
        gods = self.graph["god_nodes"]
        self.assertEqual(
            [g["id"] for g in gods],
            ["wiki/entities/alpha.md", "wiki/entities/gamma.md",
             "wiki/concepts/beta.md", "wiki/concepts/retired.md",
             "wiki/sources/severed-note.md", "wiki/queries/lonely.md"])
        alpha = gods[0]
        self.assertEqual(alpha["degree"], 6)
        self.assertEqual(alpha["in_degree"], 4)
        self.assertEqual(alpha["out_degree"], 2)
        self.assertEqual(alpha["title"], "Alpha")
        # The limit is honoured.
        top2 = self.mod.compute_god_nodes(self.graph["nodes"], limit=2)
        self.assertEqual([g["id"] for g in top2],
                         ["wiki/entities/alpha.md",
                          "wiki/entities/gamma.md"])

    def test_panels_and_filters_are_in_the_html(self):
        html = self.mod.render_html(self.graph)
        # Communities + god-nodes panels, rendered from the data.
        self.assertIn('id="communities-panel"', html)
        self.assertIn('id="god-nodes-panel"', html)
        self.assertIn('id="communities-list"', html)
        self.assertIn('id="god-nodes-list"', html)
        self.assertIn("buildPanels", html)
        self.assertIn("God nodes (top 10 by degree)", html)
        data = extract_data(html)
        self.assertEqual(len(data["communities"]), 2)
        self.assertEqual(data["god_nodes"][0]["id"],
                         "wiki/entities/alpha.md")
        self.assertEqual(data["god_nodes"][0]["in_degree"], 4)
        self.assertEqual(data["god_nodes"][0]["out_degree"], 2)
        # Client-side filters by page type and by tag.
        self.assertIn('id="filter-type"', html)
        self.assertIn('id="filter-tag"', html)
        self.assertIn('id="filter-clear"', html)
        self.assertIn("applyFilters", html)
        self.assertIn("nodeMatchesFilter", html)
        self.assertIn("buildFilters", html)
        # The data the filters consume is present per node.
        by_id = {n["id"]: n for n in data["nodes"]}
        self.assertEqual(by_id["wiki/concepts/beta.md"]["tags"],
                         ["graph", "hub"])
        self.assertEqual(by_id["wiki/entities/alpha.md"]["type"],
                         "entity")


if __name__ == "__main__":
    unittest.main()
