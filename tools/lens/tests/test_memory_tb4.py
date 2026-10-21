"""Memory-transparency + TB4 Lens wiring tests (Marathon R4 lane A).

Run from anywhere:
    python3 -m unittest tools.lens.tests.test_memory_tb4
    python3 tools/lens/tests/test_memory_tb4.py

Covers the lenslib half of the wiring: the artefact loaders
(memory transparency, relation maps, page history, related
pages), the grounded-in-N-claims computation an Ask answer's
chip renders, and the feedback record builder / triage loader
(TB4 points 1, 2, 3, 5 read sides + item 1's chip).
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
REPO = HERE.parents[3]
sys.path.insert(0, str(LENS_DIR))

import lenslib as L  # noqa: E402


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


CLAIMS = [
    {"claim_id": "wiki/concepts/alpha.md", "text": "Alpha holds.",
     "stated": "2026-01-01", "supports": 1, "contradicts": 0,
     "verified_n": 0, "superseded": False, "indexed_on": "2026-01-02",
     "hash": "h1"},
    {"claim_id": "wiki/entities/beta.md", "text": "Beta exists.",
     "stated": "2026-01-01", "supports": 0, "contradicts": 0,
     "verified_n": 0, "superseded": False, "indexed_on": "2026-01-02",
     "hash": "h2"},
]


def fixture_repo(root):
    _write(root, "evaluation/claim-index.jsonl", _jsonl(CLAIMS))
    _write(root, "evaluation/memory-transparency.json", json.dumps({
        "kind": "memory-transparency", "version": 1,
        "claims": CLAIMS, "claim_history": {}, "connections": [],
        "ask_events": []}))
    _write(root, "evaluation/relation-maps.json", json.dumps({
        "kind": "relation-maps", "edge_types": ["wikilink"],
        "edges": [], "hoisting": [
            {"page": "wiki/concepts/alpha.md", "child_count": 3,
             "children": [], "suggestion": "hoist"}]}))
    _write(root, "evaluation/page-history.json", json.dumps({
        "kind": "page-history", "pages": {
            "wiki/concepts/alpha.md": {
                "history": [{"commit": "abc1234", "date": "2026-01-02",
                             "author": "a", "subject": "s"}],
                "commits": 1, "latest_diff": "diff --git a/x b/x\n+line"}}}))
    _write(root, "evaluation/related-pages.json", json.dumps({
        "kind": "related-pages", "related": {
            "wiki/concepts/alpha.md": [
                {"page": "wiki/entities/beta.md", "score": 7.0,
                 "why": ["linked", "terms:12"]}]}}))
    return root


class Loaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.root = fixture_repo(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_memory_transparency_loads(self):
        data = L.load_memory_transparency(self.root)
        self.assertEqual(len(data["claims"]), 2)

    def test_relation_maps_loads(self):
        data = L.load_relation_maps(self.root)
        self.assertEqual(data["edge_types"], ["wikilink"])
        self.assertEqual(data["hoisting"][0]["child_count"], 3)

    def test_page_history_loads(self):
        pages = L.load_page_history(self.root)
        row = pages["wiki/concepts/alpha.md"]
        self.assertEqual(row["commits"], 1)
        self.assertIn("+line", row["latest_diff"])

    def test_related_pages_loads(self):
        related = L.load_related_pages(self.root)
        row = related["wiki/concepts/alpha.md"][0]
        self.assertEqual(row["score"], 7.0)
        self.assertEqual(row["why"], ["linked", "terms:12"])

    def test_claim_page_paths(self):
        self.assertEqual(L.claim_page_paths(self.root),
                         ["wiki/concepts/alpha.md",
                          "wiki/entities/beta.md"])


class MissingArtefacts(unittest.TestCase):
    def test_empty_tree_degrades(self):
        with TemporaryDirectory() as td:
            self.assertEqual(L.load_memory_transparency(td)["claims"], [])
            self.assertEqual(L.load_relation_maps(td), {})
            self.assertEqual(L.load_page_history(td), {})
            self.assertEqual(L.load_related_pages(td), {})
            self.assertEqual(L.claim_page_paths(td), [])


class GroundedClaims(unittest.TestCase):
    def test_count_from_cited_pages(self):
        resolve = {"alpha": "alpha", "note": "beta-note"}.get
        path_by_id = {"alpha": "wiki/concepts/alpha.md",
                      "beta-note": "wiki/concepts/beta-note.md"}
        out = L.grounded_claims(
            ["alpha", {"id": "note"}, "missing", "alpha"],
            ["wiki/concepts/alpha.md"], resolve, path_by_id)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["claim_ids"], ["wiki/concepts/alpha.md"])
        self.assertEqual(out["cited_ids"], ["alpha", "beta-note"])

    def test_path_level_form(self):
        out = L.grounded_claims_for_pages(
            ["wiki/entities/beta.md", "wiki/x.md"],
            ["wiki/concepts/alpha.md", "wiki/entities/beta.md"])
        self.assertEqual(out, {"count": 1,
                               "claim_ids": ["wiki/entities/beta.md"]})


class Feedback(unittest.TestCase):
    def test_record_builder(self):
        rec = L.make_feedback_record(
            "wiki/concepts/alpha.md", "correction", text=" wrong date ",
            ts="2026-01-05T00:00:00Z", record_id="fb-1")
        self.assertEqual(rec, {"id": "fb-1", "ts": "2026-01-05T00:00:00Z",
                               "source": "portal",
                               "page": "wiki/concepts/alpha.md",
                               "kind": "correction", "text": "wrong date"})
        thumb = L.make_feedback_record("wiki/a.md", "thumbs_up",
                                       ts="t", record_id="fb-2")
        self.assertNotIn("text", thumb)

    def test_record_builder_rejects(self):
        with self.assertRaises(ValueError):
            L.make_feedback_record("wiki/a.md", "correction")
        with self.assertRaises(ValueError):
            L.make_feedback_record("wiki/a.md", "meh")
        with self.assertRaises(ValueError):
            L.make_feedback_record("wiki/a.md", "thumbs_up", source="web")
        with self.assertRaises(ValueError):
            L.make_feedback_record("", "thumbs_up")

    def test_triage_loader(self):
        with TemporaryDirectory() as td:
            _write(td, "scripts/wiki_feedback_triage.py",
                   (REPO / "scripts/wiki_feedback_triage.py")
                   .read_text(encoding="utf-8"))
            _write(td, "evaluation/feedback.jsonl", _jsonl([
                {"id": "1", "ts": "2026-01-01", "source": "portal",
                 "page": "wiki/a.md", "kind": "thumbs_down"},
                {"id": "2", "ts": "2026-01-01", "source": "portal",
                 "page": "wiki/a.md", "kind": "correction",
                 "text": "wrong"},
                {"id": "bad", "ts": "2026-01-01", "source": "portal",
                 "page": "wiki/a.md", "kind": "nope"},
            ]))
            triage = L.load_feedback_triage(td)
        self.assertEqual(triage["total"], 2)
        self.assertEqual(len(triage["corrections"]), 1)
        self.assertTrue(triage["pages"][0]["needs_attention"])

    def test_triage_no_log(self):
        with TemporaryDirectory() as td:
            self.assertEqual(L.load_feedback_triage(td)["total"], 0)


class RealArtefacts(unittest.TestCase):
    """The loaders over this repo's own artefacts, as the build
    reads them (skips cleanly where an artefact is absent)."""

    def test_real_tree(self):
        memory = L.load_memory_transparency(REPO)
        self.assertEqual(memory["kind"], "memory-transparency")
        claims = L.claim_page_paths(REPO)
        for conn in memory.get("connections") or []:
            self.assertIn(conn["claim_id"], claims)
        for event in memory.get("ask_events") or []:
            self.assertEqual(event["grounded_claims"],
                             len(event["grounded_claim_ids"]))


if __name__ == "__main__":
    unittest.main()
