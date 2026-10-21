#!/usr/bin/env python3
"""Tests for wiki_memory_transparency (Marathon R4 lane A, item 1).

Fixture trees only: claims list, claim history (indexed + notice +
outcome events), connections (pages citing a claim + Ask events
grounded in it) and ask-events with resolved cited pages and the
grounded-in count. Also pins: missing records degrade to empty
views, the latest index record per claim wins, and the written
artefact round-trips through `check`.
"""
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "mt", ROOT / "scripts/wiki_memory_transparency.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


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
    # A later index run supersedes the form above for the same claim.
    {"claim_id": "wiki/concepts/alpha.md", "text": "Alpha holds, v2.",
     "stated": "2026-01-03", "supports": 2, "contradicts": 0,
     "verified_n": 1, "superseded": False, "indexed_on": "2026-01-04",
     "hash": "h2"},
    {"claim_id": "wiki/entities/beta.md", "text": "Beta exists.",
     "stated": "2026-01-01", "supports": 0, "contradicts": 1,
     "verified_n": 0, "superseded": True, "indexed_on": "2026-01-02",
     "hash": "h3"},
]

QA = [
    {"id": "q1", "question": "Is alpha true?", "asker": "owner",
     "asked_at": "2026-01-05T00:00:00Z", "answered_at": "2026-01-05T01:00:00Z",
     "answer": "Yes.", "citations": ["alpha", "concepts/beta-note"],
     "status": "answered"},
    {"id": "q2", "question": "Unrelated?", "asker": "owner",
     "asked_at": "2026-01-06T00:00:00Z", "answer": "No record.",
     "citations": ["missing-page"], "status": "answered"},
]


def fixture_tree(root):
    _write(root, "evaluation/claim-index.jsonl", _jsonl(CLAIMS))
    _write(root, "wiki/access/qa-2026.jsonl", _jsonl(QA))
    _write(root, "evaluation/notices.jsonl", _jsonl([
        {"by": "agent", "date": "2026-01-07", "kind": "applied",
         "notice": "claim-negative-treatment",
         "page": "wiki/entities/beta.md", "reason": "treated"},
        {"by": "agent", "date": "2026-01-07", "kind": "applied",
         "notice": "other", "page": "wiki/other.md", "reason": "n/a"},
    ]))
    _write(root, "evaluation/outcomes.jsonl", _jsonl([
        {"claim": "wiki/concepts/alpha.md", "outcome": "supports",
         "date": "2026-01-08", "by": "check"},
    ]))
    _write(root, "wiki/concepts/alpha.md",
           "---\ntitle: Alpha\n---\nAlpha claim page.\n")
    _write(root, "wiki/entities/beta.md",
           "---\ntitle: Beta\n---\nBeta claim page.\n")
    _write(root, "wiki/concepts/beta-note.md",
           "---\ntitle: Note\n---\nThis note cites [[alpha]] and "
           "[[beta]] in prose.\n")
    _write(root, "wiki/overview.md",
           "---\ntitle: Overview\n---\nSee [[concepts/alpha]].\n")
    return root


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.data = m.build_transparency(fixture_tree(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_claims_latest_wins(self):
        claims = {c["claim_id"]: c for c in self.data["claims"]}
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims["wiki/concepts/alpha.md"]["text"],
                         "Alpha holds, v2.")
        self.assertEqual(claims["wiki/concepts/alpha.md"]["supports"], 2)

    def test_claim_history_events(self):
        hist = self.data["claim_history"]["wiki/concepts/alpha.md"]
        kinds = [e["event"] for e in hist]
        self.assertEqual(kinds.count("indexed"), 2)
        self.assertIn("outcome", kinds)
        beta = self.data["claim_history"]["wiki/entities/beta.md"]
        self.assertEqual([e["event"] for e in beta],
                         ["indexed", "notice-applied"])
        self.assertEqual(beta[1]["notice"], "claim-negative-treatment")

    def test_connections(self):
        conn = {c["claim_id"]: c for c in self.data["connections"]}
        alpha = conn["wiki/concepts/alpha.md"]
        self.assertEqual(alpha["page"], "wiki/concepts/alpha.md")
        self.assertEqual(alpha["cited_by_pages"],
                         ["wiki/concepts/beta-note.md", "wiki/overview.md"])
        self.assertEqual(alpha["ask_event_ids"], ["q1"])
        beta = conn["wiki/entities/beta.md"]
        self.assertEqual(beta["cited_by_pages"],
                         ["wiki/concepts/beta-note.md"])

    def test_ask_events_grounded(self):
        ev = {e["id"]: e for e in self.data["ask_events"]}
        self.assertEqual(ev["q1"]["cited_pages"],
                         ["wiki/concepts/alpha.md",
                          "wiki/concepts/beta-note.md"])
        self.assertEqual(ev["q1"]["grounded_claims"], 1)
        self.assertEqual(ev["q1"]["grounded_claim_ids"],
                         ["wiki/concepts/alpha.md"])
        self.assertEqual(ev["q2"]["cited_pages"], [])
        self.assertEqual(ev["q2"]["grounded_claims"], 0)

    def test_sources_counts(self):
        self.assertEqual(self.data["sources"]["claim_index_records"], 3)
        self.assertEqual(self.data["sources"]["claims"], 2)
        self.assertEqual(self.data["sources"]["ask_records"], 2)


class EmptyTree(unittest.TestCase):
    def test_missing_records_degrade(self):
        with TemporaryDirectory() as td:
            data = m.build_transparency(td)
        self.assertEqual(data["claims"], [])
        self.assertEqual(data["claim_history"], {})
        self.assertEqual(data["connections"], [])
        self.assertEqual(data["ask_events"], [])


class CliRoundTrip(unittest.TestCase):
    def test_build_then_check(self):
        with TemporaryDirectory() as td:
            fixture_tree(td)
            self.assertEqual(m.main(["--root", td, "build"]), 0)
            out = Path(td) / "evaluation/memory-transparency.json"
            self.assertTrue(out.is_file())
            self.assertEqual(m.main(["--root", td, "check"]), 0)
            out.write_text("{}\n", encoding="utf-8")
            self.assertEqual(m.main(["--root", td, "check"]), 1)


class GroundedHelper(unittest.TestCase):
    def test_dict_citations(self):
        key_map = m.page_key_map(["wiki/concepts/alpha.md"])
        cited, grounded = m.grounded_claims(
            [{"page_id": "alpha"}, "nope"], {"wiki/concepts/alpha.md"},
            key_map)
        self.assertEqual(cited, ["wiki/concepts/alpha.md"])
        self.assertEqual(grounded, ["wiki/concepts/alpha.md"])


if __name__ == "__main__":
    unittest.main()
