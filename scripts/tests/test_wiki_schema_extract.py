"""Tests for scripts/wiki_schema_extract.py — the DeepKE/
OneKE-style schema-guided extraction pass: proposals are
generated deterministically from a fixed schema (heading /
capitalised-term / wikilink heuristics + cue-phrase
relations), in a gateway-shaped envelope, and NOTHING is
auto-applied — source bytes and the page tree are byte-
identical before and after.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_schema_extract as wse  # noqa: E402

SOURCE = """---
title: Demo Source
date: 2026-10-21
---

# The Lantern Project

Dr Ines Halden leads the Lantern Project.
Ines Halden works for the Northwind Institute.
The project page links to [[harbour-notes]].

## Harbour Notes

The Harbour Notes describe the lantern archive.
"""

SCHEMA = {
    "schema_version": 1,
    "default_entity_type": "Concept",
    "entities": [
        {"type": "Person", "cues": ["Dr"]},
        {"type": "Organization", "cues": []},
        {"type": "Place", "cues": []},
        {"type": "Concept", "cues": []},
    ],
    "relations": [
        {"type": "mentions", "cue_phrases": []},
        {"type": "works-for", "cue_phrases": ["works for"]},
        {"type": "located-in", "cue_phrases": ["based in"]},
        {"type": "leads", "cue_phrases": ["leads"]},
    ],
}


def tree_hashes(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class SchemaExtractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="extract-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "evaluation").mkdir()
        (self.root / "raw" / "sources").mkdir(parents=True)
        self.schema = self.root / "evaluation" / \
            "extraction-schema.json"
        self.schema.write_text(json.dumps(SCHEMA),
                               encoding="utf-8")
        self.source = self.root / "raw" / "sources" / "demo.md"
        self.source.write_text(SOURCE, encoding="utf-8")

    def test_proposals_generated_against_schema(self):
        payload = wse.build_proposals(
            self.root, "raw/sources/demo.md")
        names = {e["name"]: e["type"]
                 for e in payload["proposals"]["entities"]}
        self.assertIn("Lantern Project", names)
        self.assertIn("Ines Halden", names)
        self.assertEqual(names["Ines Halden"], "Person")
        self.assertIn("harbour-notes", names)
        rels = {(r["type"], r["subject"], r["object"])
                for r in payload["proposals"]["relations"]}
        self.assertIn(("works-for", "Ines Halden",
                       "Northwind Institute"), rels)
        self.assertIn(("mentions", "raw/sources/demo.md",
                       "harbour-notes"), rels)
        # Every proposed type comes from the fixed schema.
        for e in payload["proposals"]["entities"]:
            self.assertIn(e["type"],
                          payload["schema_types"]["entities"])
        for r in payload["proposals"]["relations"]:
            self.assertIn(r["type"],
                          payload["schema_types"]["relations"])

    def test_gateway_shaped_envelope_and_never_applied(self):
        payload = wse.build_proposals(
            self.root, "raw/sources/demo.md")
        for key in ("proposal_id", "state", "submitted_by",
                    "target_path", "sha256", "bytes", "cites",
                    "submitted_at"):
            self.assertIn(key, payload)
        self.assertEqual(payload["state"], "draft")
        self.assertIs(payload["applied"], False)
        self.assertEqual(payload["submitted_at"], "2026-10-21")
        self.assertEqual(payload["cites"],
                         ["raw/sources/demo.md"])

    def test_nothing_is_auto_applied(self):
        before = tree_hashes(self.root)
        out = self.root / "out" / "proposals.json"
        report = self.root / "out" / "report.txt"
        rc = wse.main(["--root", str(self.root),
                       "raw/sources/demo.md",
                       "--out", str(out),
                       "--report", str(report)])
        self.assertEqual(rc, 0)
        after = tree_hashes(self.root)
        for rel, digest in before.items():
            self.assertEqual(after[rel], digest, rel)
        self.assertFalse((self.root / "wiki").exists())
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertIs(payload["applied"], False)
        self.assertIn("applied: false",
                      report.read_text(encoding="utf-8"))

    def test_scaffold_schema_in_tree_is_valid(self):
        real = SCRIPTS.parent / "evaluation" / \
            "extraction-schema.json"
        schema = wse.load_schema(real)
        self.assertIn("Concept",
                      [e["type"] for e in schema["entities"]])
        payload = wse.build_proposals(
            self.root, "raw/sources/demo.md")
        self.assertGreater(payload["counts"]["entities"], 0)

    def test_missing_source_and_schema_refused(self):
        with self.assertRaises(wse.ExtractError):
            wse.build_proposals(self.root, "raw/sources/nope.md")
        bad = self.root / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        with self.assertRaises(wse.ExtractError):
            wse.build_proposals(self.root, "raw/sources/demo.md",
                                schema_path=bad)


if __name__ == "__main__":
    unittest.main()
