"""Tests for Prompt Capsules (Marathon R2 lane B1).

``tools/ask/capsules.py``: a capsule is a markdown file with
frontmatter (name, description) and a list of page paths to
pin. When a question names a capsule (exact name match), its
pages are packed FIRST by ``evidence_packing.pack_evidence``
— subject to the same severance rules: a severed page in a
capsule is NOT packed.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_capsules -v
or directly:
    python3 tools/ask/tests/test_capsules.py

No network is used; the wiki and capsules live in temp dirs,
plus a parse-only check of the capsule shipped at the tree
root of this scratch/real tree.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capsules  # noqa: E402
import evidence_packing  # noqa: E402

CAPSULE_TEXT = """---
name: field-notes
description: Field-note pages pinned for field questions.
---

# Prompt Capsule — field-notes

- sources/alpha
- sources/retired-page
- [[sources/beta]]
"""

SEVERANCE = {
    "kind": "retrieval-severance",
    "version": 1,
    "entries": [
        {
            "id": "sev-test-0001",
            "kind": "page",
            "page": "wiki/sources/retired-page.md",
            "claim": None,
            "cues": {"phrases": [], "terms": ["retired"]},
            "source": {
                "register": "wiki/ frontmatter",
                "line": None,
                "record_id": "wiki/sources/retired-page.md",
                "signal": "status: superseded",
            },
        },
    ],
}


def make_wiki(root: Path):
    wiki = root / "wiki"
    (wiki / "sources").mkdir(parents=True)
    (wiki / "sources" / "alpha.md").write_text(
        "Alpha page evidence text.", encoding="utf-8"
    )
    (wiki / "sources" / "beta.md").write_text(
        "Beta page evidence text.", encoding="utf-8"
    )
    (wiki / "sources" / "retired-page.md").write_text(
        "Retired page evidence text.", encoding="utf-8"
    )
    return wiki


class ParseCapsuleTests(unittest.TestCase):
    def test_frontmatter_and_pins(self):
        capsule = capsules.parse_capsule(CAPSULE_TEXT)
        self.assertEqual(capsule["name"], "field-notes")
        self.assertIn("Field-note pages", capsule["description"])
        self.assertEqual(
            capsule["pages"],
            ["sources/alpha", "sources/retired-page",
             "sources/beta"],
        )

    def test_bare_stem_list_item_is_a_pin(self):
        capsule = capsules.parse_capsule(
            "---\nname: bare\ndescription: Bare stems.\n---\n\n"
            "- overview\n- sources/alpha\n"
            "A prose line mentioning sources/alpha in passing.\n"
        )
        self.assertEqual(
            capsule["pages"], ["overview", "sources/alpha"]
        )

    def test_shipped_example_capsule_parses(self):
        # The capsule shipped at this tree's root (the lane
        # scratch mirrors the tree layout: capsules/ beside
        # tools/). Parse-only: its pages live in the real wiki,
        # which a scratch copy may not carry.
        shipped = capsules.load_capsules()
        self.assertTrue(shipped, "no shipped capsule found")
        for capsule in shipped:
            self.assertTrue(capsule["name"])
            self.assertTrue(capsule["description"])
            self.assertTrue(capsule["pages"])


class FindCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.capsule = capsules.parse_capsule(CAPSULE_TEXT)

    def test_exact_name_match_in_question(self):
        found = capsules.find_capsule(
            "Using field-notes, what do the notes say?",
            [self.capsule],
        )
        self.assertIs(found, self.capsule)

    def test_substring_is_not_a_match(self):
        self.assertIsNone(
            capsules.find_capsule(
                "Tell me about field-notesXYZ please",
                [self.capsule],
            )
        )
        self.assertIsNone(
            capsules.find_capsule(
                "An unrelated question entirely", [self.capsule]
            )
        )


class CapsulePackingTests(unittest.TestCase):
    def test_capsule_pages_packed_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(Path(tmp))
            capsule = capsules.parse_capsule(CAPSULE_TEXT)
            pinned = capsules.capsule_passages(capsule, wiki)
            self.assertEqual(
                [p["page"] for p in pinned],
                ["sources/alpha", "sources/retired-page",
                 "sources/beta"],
            )
            self.assertTrue(all(p["pinned"] for p in pinned))
            rival = {
                "page": "overview", "passage": "Rival evidence.",
                "score": 0.99,
            }
            # Budget fits the rival's short text plus ONE pinned
            # page-sized chunk many times over — but pinned
            # passages are considered first, so under a budget
            # that fits exactly two passages the capsule wins.
            budget = evidence_packing.estimate_tokens(
                pinned[0]["passage"]
            ) * 2
            result = evidence_packing.pack_evidence(
                pinned + [rival], budget=budget
            )
            self.assertEqual(
                [p["page"] for p in result["packed"]],
                ["sources/alpha", "sources/retired-page"],
            )
            self.assertEqual(
                [p["page"] for p in result["dropped"]],
                ["sources/beta", "overview"],
            )

    def test_severed_capsule_page_is_not_packed(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(Path(tmp))
            capsule = capsules.parse_capsule(CAPSULE_TEXT)
            pinned = capsules.capsule_passages(capsule, wiki)
            result = evidence_packing.pack_evidence(
                pinned, severance=SEVERANCE
            )
            packed_pages = [p["page"] for p in result["packed"]]
            self.assertNotIn("sources/retired-page", packed_pages)
            self.assertEqual(
                packed_pages, ["sources/alpha", "sources/beta"]
            )
            # The cut is on the record, never silent.
            self.assertEqual(len(result["severed"]), 1)
            cut = result["severed"][0]
            self.assertEqual(cut["page"], "sources/retired-page")
            self.assertEqual(cut["severed_by"], "sev-test-0001")
            self.assertEqual(cut["reason"], "severed")

    def test_pinned_candidates_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = make_wiki(root)
            cap_dir = root / "capsules"
            cap_dir.mkdir()
            (cap_dir / "field-notes.md").write_text(
                CAPSULE_TEXT, encoding="utf-8"
            )
            capsule, passages = capsules.pinned_candidates(
                "With field-notes in mind, summarise the notes.",
                wiki_dir=wiki, capsules_dir=cap_dir,
            )
            self.assertEqual(capsule["name"], "field-notes")
            self.assertEqual(len(passages), 3)
            capsule, passages = capsules.pinned_candidates(
                "A question naming nothing.",
                wiki_dir=wiki, capsules_dir=cap_dir,
            )
            self.assertIsNone(capsule)
            self.assertEqual(passages, [])

    def test_missing_pinned_page_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(Path(tmp))
            capsule = {
                "name": "x", "description": "",
                "pages": ["sources/alpha", "sources/ghost"],
            }
            passages = capsules.capsule_passages(capsule, wiki)
            self.assertEqual(
                [p["page"] for p in passages], ["sources/alpha"]
            )


if __name__ == "__main__":
    unittest.main()
