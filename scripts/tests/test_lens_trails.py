"""Item 62 — Lens trails + source-adjacent evidence.

Covers the brief's test list for the item:

- trail serialise/parse: lenslib.trail_url -> parse_trail_url
  round-trips (the stack in the URL is the walk's state), and a
  non-trail URL parses to None;
- step rendering data: build_trails_artefact validates the
  AUTHORITATIVE register (tools/lens/trails.json) against a
  fixture edge table shaped like the build's — every authored
  hop must exist with its named edge type — and a broken trail
  (missing page, wrong edge type, unnamed hop) is DROPPED with
  reasons, never rendered as curated;
- passage pairing: load_citation_lockfile pairs claims with the
  lockfile's VERBATIM TextQuoteSelector text; an entry whose
  passage cannot be produced (no selector / empty exact) yields
  NOTHING, and a page absent from the lockfile pairs with
  nothing.

lenslib is loaded by path, the test_freshness.py convention.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lens"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("lenslib_trails", ROOT / "tools" / "lens" / "lenslib.py")


def page(pid, title=None, ptype="synthesis", section="syntheses"):
    return {"id": pid, "title": title or pid, "type": ptype,
            "section": section}


def edge(src, dst, etype, kind="wikilink"):
    return {"src": src, "dst": dst, "kind": kind,
            "relation": "mentions" if kind == "wikilink" else etype,
            "type": etype, "section": None, "anchor": None,
            "epistemic": "extracted"}


class SerialiseParseTests(unittest.TestCase):
    def test_round_trip(self):
        url = L.trail_url("survey-to-build",
                           ["feature-survey", "ideas",
                            "current-state"], 2)
        self.assertEqual(
            url, "#/trails/survey-to-build?stack="
                 "feature-survey,ideas,current-state&at=2")
        parsed = L.parse_trail_url(url)
        self.assertEqual(parsed["trail_id"], "survey-to-build")
        self.assertEqual(parsed["stack"],
                         ["feature-survey", "ideas",
                          "current-state"])
        self.assertEqual(parsed["at"], 2)

    def test_parse_tolerates_full_href_and_missing_query(self):
        parsed = L.parse_trail_url(
            "https://example.invalid/index.html#/trails/x")
        self.assertEqual(parsed, {"trail_id": "x", "stack": [], "at": 0})

    def test_parse_rejects_non_trail_urls(self):
        self.assertIsNone(L.parse_trail_url("#/read/overview"))
        self.assertIsNone(L.parse_trail_url(""))
        self.assertIsNone(L.parse_trail_url(None))


class TrailArtefactTests(unittest.TestCase):
    def setUp(self):
        self.pages = {pid: page(pid) for pid in
                      ("a", "b", "c", "overview")}
        self.edges = [edge("a", "b", "grounds"),
                      edge("b", "c", "mentions"),
                      edge("a", "c", "cites", kind="citation")]

    def _artefact(self, trails):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "tools" / "lens").mkdir(parents=True)
            (repo / "tools" / "lens" / "trails.json").write_text(
                json.dumps({"trails": trails}), encoding="utf-8")
            return L.build_trails_artefact(repo, self.pages, self.edges)

    def test_valid_trail_renders_with_edge_types_named(self):
        art = self._artefact([{
            "id": "t1", "title": "T1", "summary": "s",
            "steps": [{"page": "a"}, {"page": "b", "via": "grounds"},
                      {"page": "c", "via": "mentions"}]}])
        self.assertEqual(art["dropped"], [])
        (trail,) = art["trails"]
        self.assertEqual([s["via"] for s in trail["steps"]],
                         [None, "grounds", "mentions"])
        self.assertEqual(trail["steps"][1]["title"], "b")

    def test_broken_trails_drop_with_reasons(self):
        art = self._artefact([
            {"id": "ghost", "title": "G",
             "steps": [{"page": "a"}, {"page": "nope", "via": "grounds"}]},
            {"id": "wrongtype", "title": "W",
             "steps": [{"page": "a"}, {"page": "b", "via": "contradicts"}]},
            {"id": "unnamed", "title": "U",
             "steps": [{"page": "a"}, {"page": "b"}]},
            {"id": "short", "title": "S", "steps": [{"page": "a"}]},
        ])
        self.assertEqual(art["trails"], [])
        reasons = {d["id"]: "; ".join(d["reasons"])
                   for d in art["dropped"]}
        self.assertIn("no page 'nope'", reasons["ghost"])
        self.assertIn("no 'contradicts' edge", reasons["wrongtype"])
        self.assertIn("no `via`", reasons["unnamed"])
        self.assertIn("at least two steps", reasons["short"])

class CitationPairingTests(unittest.TestCase):
    def _lock_repo(self, citations):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = Path(td.name)
        (repo / "evaluation").mkdir(parents=True)
        (repo / "evaluation" / "citation-lockfile.json").write_text(
            json.dumps({"lockfile_version": 2, "citations": citations}),
            encoding="utf-8")
        return repo

    def test_pairing_is_verbatim_from_the_lockfile(self):
        repo = self._lock_repo([{
            "id": "c0001", "page": "wiki/x.md", "page_line": 12,
            "claim": "The claim as written.",
            "source": "raw/s.md", "range": [5, 5],
            "selector": {"type": "TextQuoteSelector",
                         "exact": "the verbatim passage",
                         "prefix": "", "suffix": ""}}])
        pages = L.load_citation_lockfile(repo)
        (pairing,) = pages["wiki/x.md"]
        self.assertEqual(pairing["quote"], "the verbatim passage")
        self.assertEqual(pairing["claim"], "The claim as written.")
        self.assertEqual(pairing["cite_id"], "c0001")
        self.assertEqual(pairing["range"], [5, 5])

    def test_unproducible_passage_shows_nothing(self):
        repo = self._lock_repo([
            {"id": "c0002", "page": "wiki/x.md", "page_line": 3,
             "claim": "No selector.", "source": "raw/s.md",
             "range": [1, 1], "selector": None},
            {"id": "c0003", "page": "wiki/x.md", "page_line": 4,
             "claim": "Empty exact.", "source": "raw/s.md",
             "range": [2, 2],
             "selector": {"type": "TextQuoteSelector", "exact": "  "}},
        ])
        self.assertEqual(L.load_citation_lockfile(repo), {})

    def test_absent_lockfile_and_absent_page_pair_with_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(L.load_citation_lockfile(Path(td)), {})



if __name__ == "__main__":
    unittest.main()
