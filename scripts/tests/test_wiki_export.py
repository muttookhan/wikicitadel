#!/usr/bin/env python3
"""Tests for scripts/wiki_export.py (JSON-LD / GraphML / Marp)
and scripts/wiki_import.py (15-gap item 10, plus the Marp
slice of item 15).

On a FIXTURE wiki in a temp dir (driven through the real CLIs
with --root, never the live corpus):

  - jsonld parses as JSON, holds one node per compiled page
    (@id = repo-relative path, with title/type/tags/stage/
    status), every typed + untyped wikilink and frontmatter
    relation as a relation entry (grounds from an Evidence
    heading, contradicts from a Disagreements heading,
    mentions for an untyped link, supersedes and
    is-superseded-by from frontmatter), and the tombstoned
    page present and MARKED (status tombstoned, tombstoned
    true, its reason carried) — never dropped;
  - graphml parses as XML (xml.etree) with node/edge counts
    matching the JSON-LD graph, node title/type/status data
    and edge relation data;
  - marp emits `marp: true` frontmatter, a title slide plus
    one slide per requested page, each slide carrying the
    page's own text and its source citations;
  - import DRY-RUN writes nothing at all; import --apply
    preserves the vault files' bytes exactly under
    raw/sources/imported-<date>/, writes stub source pages
    with proper frontmatter (type source, tags incl.
    `imported`, sources pointing at the preserved file) whose
    bodies record the original path, the import date and the
    pending-compile state; a second --apply run reports
    collisions and changes nothing.

Run:  python3 -m unittest scripts.tests.test_wiki_export -v
  or  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
EXPORT_TOOL = SCRIPTS / "wiki_export.py"
IMPORT_TOOL = SCRIPTS / "wiki_import.py"
IMPORT_DATE = "2026-10-20"

ALPHA = """---
title: Alpha
type: concept
created: 2026-10-12
updated: 2026-10-13
sources:
  - raw/sources/alpha-note.md
tags: [fixture, alpha]
stage: budding
status: active
---

# Alpha

Alpha explains the fixture graph in plain words, and mentions
[[gamma]] here before any heading types the link.

## Evidence

Alpha rests on [[beta]].

## Disagreements

The other side is [[gamma]].
"""

BETA = """---
title: Beta
type: concept
created: 2026-10-13
updated: 2026-10-13
sources: [raw/sources/beta-note.md]
tags: [fixture]
stage: seedling
status: draft
supersedes:
  - wiki/concepts/gamma.md
---

# Beta

Beta extends the story with its own unique sentence.
"""

GAMMA = """---
title: Gamma
type: entity
created: 2026-10-14
updated: 2026-10-14
sources: []
tags: [fixture]
status: active
---

# Gamma

## Notes

Gamma links back to [[alpha]] in a neutral section.
"""

TOMBSTONE = """---
title: Old Page
type: source
created: 2026-10-01
updated: 2026-10-19
sources: []
tags: [fixture, retired]
status: tombstoned
tombstoned: 2026-10-19
tombstone_reason: "Retired in the fixture."
replaced_by: wiki/concepts/alpha.md
---

# Old Page

> [!warning] Tombstone — this page was retired on 2026-10-19
> Retired in the fixture.
"""

# The fixture graph, by hand: 4 nodes, 6 edges.
EXPECTED_EDGES = {
    ("wiki/concepts/alpha.md", "wiki/concepts/gamma.md", "mentions"),
    ("wiki/concepts/alpha.md", "wiki/concepts/beta.md", "grounds"),
    ("wiki/concepts/alpha.md", "wiki/concepts/gamma.md", "contradicts"),
    ("wiki/concepts/beta.md", "wiki/concepts/gamma.md", "supersedes"),
    ("wiki/concepts/gamma.md", "wiki/concepts/alpha.md", "mentions"),
    ("wiki/sources/old-page.md", "wiki/concepts/alpha.md",
     "is-superseded-by"),
}


def local(tag):
    return tag.rsplit("}", 1)[-1]


def jsonld_edges(doc):
    edges = set()
    for node in doc["@graph"]:
        for key, value in node.items():
            if isinstance(value, list) and value and isinstance(
                    value[0], dict) and "@id" in value[0]:
                for entry in value:
                    edges.add((node["@id"], entry["@id"], key))
    return edges


def graphml_graph(text):
    root_el = ET.fromstring(text)
    graph = next(el for el in root_el.iter() if local(el.tag) == "graph")
    nodes, edges = {}, []
    for el in graph:
        if local(el.tag) == "node":
            data = {d.get("key"): (d.text or "")
                    for d in el if local(d.tag) == "data"}
            nodes[el.get("id")] = data
        elif local(el.tag) == "edge":
            data = {d.get("key"): (d.text or "")
                    for d in el if local(d.tag) == "data"}
            edges.append((el.get("source"), el.get("target"),
                          data.get("relation")))
    return nodes, edges


class ExportFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="export-fixture-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        concepts = self.root / "wiki" / "concepts"
        sources = self.root / "wiki" / "sources"
        concepts.mkdir(parents=True)
        sources.mkdir(parents=True)
        (concepts / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (concepts / "beta.md").write_text(BETA, encoding="utf-8")
        (concepts / "gamma.md").write_text(GAMMA, encoding="utf-8")
        (sources / "old-page.md").write_text(TOMBSTONE,
                                             encoding="utf-8")
        # Structural pages must NOT become nodes.
        (self.root / "wiki" / "index.md").write_text(
            "# Index\n", encoding="utf-8")
        (self.root / "wiki" / "log.md").write_text(
            "# Log\n", encoding="utf-8")

    def run_export(self, *args):
        proc = subprocess.run(
            [sys.executable, str(EXPORT_TOOL),
             "--root", str(self.root), *args],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        return proc

    def jsonld_doc(self):
        return json.loads(self.run_export("jsonld").stdout)


class TestJsonLd(ExportFixture):
    def test_nodes_carry_the_page_record(self):
        doc = self.jsonld_doc()
        nodes = {n["@id"]: n for n in doc["@graph"]}
        self.assertEqual(set(nodes), {
            "wiki/concepts/alpha.md", "wiki/concepts/beta.md",
            "wiki/concepts/gamma.md", "wiki/sources/old-page.md"})
        alpha = nodes["wiki/concepts/alpha.md"]
        self.assertEqual(alpha["title"], "Alpha")
        self.assertEqual(alpha["type"], "concept")
        self.assertEqual(alpha["tags"], ["fixture", "alpha"])
        self.assertEqual(alpha["stage"], "budding")
        self.assertEqual(alpha["status"], "active")
        self.assertEqual(alpha["sources"],
                         ["raw/sources/alpha-note.md"])
        self.assertFalse(alpha["tombstoned"])

    def test_edges_typed_and_untyped(self):
        doc = self.jsonld_doc()
        self.assertEqual(jsonld_edges(doc), EXPECTED_EDGES)

    def test_out_file_matches_stdout(self):
        out = self.tmp / "corpus.json"
        self.run_export("jsonld", "--out", str(out))
        self.assertEqual(json.loads(out.read_text("utf-8")),
                         self.jsonld_doc())

    def test_tombstone_included_and_marked(self):
        doc = self.jsonld_doc()
        nodes = {n["@id"]: n for n in doc["@graph"]}
        old = nodes["wiki/sources/old-page.md"]
        self.assertEqual(old["status"], "tombstoned")
        self.assertTrue(old["tombstoned"])
        self.assertEqual(old["tombstone_date"], "2026-10-19")
        self.assertEqual(old["tombstone_reason"],
                         "Retired in the fixture.")
        self.assertEqual(old["replaced_by"],
                         "wiki/concepts/alpha.md")


class TestGraphMl(ExportFixture):
    def test_graphml_parses_and_matches_jsonld(self):
        nodes, edges = graphml_graph(self.run_export("graphml").stdout)
        doc = self.jsonld_doc()
        self.assertEqual(len(nodes), len(doc["@graph"]))
        self.assertEqual(len(nodes), 4)
        self.assertEqual(set(edges), jsonld_edges(doc))
        self.assertEqual(set(edges), EXPECTED_EDGES)

    def test_graphml_node_and_edge_data(self):
        nodes, _edges = graphml_graph(self.run_export("graphml").stdout)
        alpha = nodes["wiki/concepts/alpha.md"]
        self.assertEqual(alpha["title"], "Alpha")
        self.assertEqual(alpha["type"], "concept")
        self.assertEqual(alpha["status"], "active")
        self.assertEqual(alpha["tombstoned"], "false")
        old = nodes["wiki/sources/old-page.md"]
        self.assertEqual(old["status"], "tombstoned")
        self.assertEqual(old["tombstoned"], "true")


class TestMarp(ExportFixture):
    def slides(self, text):
        self.assertTrue(text.startswith("---\nmarp: true\n"),
                        text[:80])
        after_fm = text.split("---\n", 2)[2]
        return [s.strip() for s in after_fm.split("\n---\n")]

    def test_single_page_deck(self):
        text = self.run_export("marp", "--page", "alpha").stdout
        slides = self.slides(text)
        self.assertEqual(len(slides), 2)  # title + the page
        self.assertIn("# Alpha", slides[0])
        page_slide = slides[1]
        self.assertIn("## Alpha", page_slide)
        # The page's own text, verbatim.
        self.assertIn(
            "Alpha explains the fixture graph in plain words",
            page_slide)
        # Its source citations, listed.
        self.assertIn("raw/sources/alpha-note.md", page_slide)

    def test_multi_page_deck(self):
        text = self.run_export("marp", "--pages",
                               "alpha,beta").stdout
        slides = self.slides(text)
        self.assertEqual(len(slides), 3)  # title + 2 pages
        self.assertIn("Alpha", slides[0])
        self.assertIn("Beta", slides[0])
        self.assertIn(
            "Beta extends the story with its own unique sentence.",
            slides[2])
        self.assertIn("raw/sources/beta-note.md", slides[2])

    def test_unknown_page_refused(self):
        proc = subprocess.run(
            [sys.executable, str(EXPORT_TOOL),
             "--root", str(self.root), "marp", "--page", "nope"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no such page", proc.stderr)


# ------------------------------------------------------------ import

FIRST = b"# First Note\n\nFirst vault body, kept  verbatim.\n"
SECOND = (b"---\ntitle: Second Note\n---\n\n"
          b"Second body: caf\xc3\xa9 \xe2\x80\x94 no trailing newline")
DEEP = b"Deep file bytes\r\nwith CRLF and trailing spaces   \n"


def tree_snapshot(root):
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class ImportFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="import-fixture-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.vault = self.tmp / "vault"
        (self.vault / "notes").mkdir(parents=True)
        (self.vault / "sub").mkdir()
        (self.vault / "notes" / "first.md").write_bytes(FIRST)
        (self.vault / "second.md").write_bytes(SECOND)
        (self.vault / "sub" / "deep.md").write_bytes(DEEP)
        (self.vault / "asset.txt").write_text("not markdown\n",
                                              encoding="utf-8")
        self.raw_dir = (self.root / "raw" / "sources"
                        / ("imported-" + IMPORT_DATE))

    def run_import(self, *args):
        return subprocess.run(
            [sys.executable, str(IMPORT_TOOL),
             "--root", str(self.root), "import", str(self.vault),
             "--date", IMPORT_DATE, *args],
            capture_output=True, text=True)

    def apply(self):
        proc = self.run_import("--apply")
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        return proc


class TestImportDryRun(ImportFixture):
    def test_dry_run_writes_nothing(self):
        before = tree_snapshot(self.root)
        proc = self.run_import()
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("DRY RUN", proc.stdout)
        self.assertIn("notes/first.md", proc.stdout)
        self.assertIn("would import", proc.stdout)
        self.assertEqual(tree_snapshot(self.root), before)
        self.assertFalse(self.raw_dir.exists())
        self.assertFalse((self.root / "wiki").exists())


class TestImportApply(ImportFixture):
    def test_apply_preserves_bytes_and_writes_stubs(self):
        proc = self.apply()
        self.assertIn("imported", proc.stdout)
        pairs = (
            ("notes/first.md", FIRST), ("second.md", SECOND),
            ("sub/deep.md", DEEP))
        for rel, want in pairs:
            dest = self.raw_dir / rel
            self.assertTrue(dest.is_file(), rel)
            self.assertEqual(dest.read_bytes(), want, rel)
        self.assertFalse((self.raw_dir / "asset.txt").exists())

        stub = self.root / "wiki" / "sources" / \
            "imported-notes-first.md"
        self.assertTrue(stub.is_file())
        text = stub.read_text("utf-8")
        self.assertIn("type: source", text)
        self.assertIn("tags: [imported]", text)
        self.assertIn("created: " + IMPORT_DATE, text)
        self.assertIn(
            "raw/sources/imported-%s/notes/first.md" % IMPORT_DATE,
            text)
        # Body: original path, import date, pending-compile state.
        self.assertIn("notes/first.md", text)
        self.assertIn(IMPORT_DATE, text)
        self.assertIn("pending compile", text)
        self.assertIn("First Note", text)  # the file's own H1 title

        second = (self.root / "wiki" / "sources"
                  / "imported-second.md").read_text("utf-8")
        self.assertIn("Second Note", second)  # frontmatter title

    def test_second_run_skips_collisions_and_changes_nothing(self):
        self.apply()
        before = tree_snapshot(self.root)
        proc = self.run_import("--apply")
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("SKIP (collision)", proc.stdout)
        self.assertIn("3 skipped on collision", proc.stdout)
        self.assertEqual(tree_snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
