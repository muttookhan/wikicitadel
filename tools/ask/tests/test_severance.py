"""Tests for Ask-door severance (item 20, part c).

Covers ``tools/ask/severance.py`` (register lookup over candidate
evidence passages) and its wiring into
``tools/ask/evidence_packing.py``: a passage carrying a severed
claim — or lifted from a severed page — is cut before packing,
the cut is recorded with the register line behind it, unsevered
passages are untouched, and when every candidate is severed the
pack result flags ``all_evidence_severed`` (the abstention
signal). The fixture severance list mirrors the shape
``scripts/wiki_severance.py`` generates.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_severance -v
or directly:
    python3 tools/ask/tests/test_severance.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence_packing  # noqa: E402
import severance  # noqa: E402

SEVERANCE = {
    "kind": "retrieval-severance",
    "version": 1,
    "entries": [
        {
            "id": "sev-0001",
            "kind": "decision-form",
            "page": "wiki/syntheses/decision-register.md",
            "claim": "Collaborator's seat stays RESERVED",
            "cues": {
                "phrases": [["seat", "stays", "reserved"],
                            ["seat", "reserved"],
                            ["collaborator", "reserved"]],
                "terms": ["collaborator", "reserved", "seat", "stays"],
            },
            "source": {
                "register": "evaluation/decisions-register.jsonl",
                "line": 2,
                "record_id": "d1-reserved",
                "signal": "superseded form of decision D1",
            },
        },
        {
            "id": "sev-0002",
            "kind": "treatment",
            "page": "wiki/sources/import-policy.md",
            "claim": "a standing always-allow exists for bulk "
                     "import actions",
            "cues": {
                "phrases": [],
                "terms": ["actions", "allow", "always", "bulk",
                          "exists", "import", "standing"],
            },
            "source": {
                "register": "evaluation/treatment-register.jsonl",
                "line": 3,
                "record_id": "treat-0002",
                "signal": "negative treatment (standing grade)",
            },
        },
        {
            "id": "sev-0003",
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


def passage(page, text, score=0.9):
    return {"page": page, "passage": text, "score": score}


class FilterPassagesTests(unittest.TestCase):
    def test_form_phrase_severs_from_any_page(self):
        # The dead form resurfacing on an unrelated page is still
        # the dead claim: the passage is cut, with its citation.
        p = passage("syntheses/current-state",
                    "As recorded, Collaborator's seat stays RESERVED "
                    "pending a ruling.")
        out = severance.filter_passages([p], SEVERANCE)
        self.assertEqual(out["kept"], [])
        self.assertEqual(len(out["severed"]), 1)
        rec = out["severed"][0]
        self.assertEqual(rec["severed_by"], "sev-0001")
        self.assertEqual(rec["source"]["register"],
                         "evaluation/decisions-register.jsonl")
        self.assertEqual(rec["source"]["line"], 2)
        self.assertTrue(out["all_evidence_severed"])

    def test_treatment_terms_sever_the_claim(self):
        p = passage("sources/import-policy",
                    "The note claimed a standing always-allow "
                    "exists for bulk import actions.")
        out = severance.filter_passages([p], SEVERANCE)
        self.assertEqual([r["severed_by"] for r in out["severed"]],
                         ["sev-0002"])

    def test_severed_page_cuts_innocuous_text(self):
        p = passage("sources/retired-page",
                    "Nothing in this passage states any claim "
                    "under dispute at all.")
        out = severance.filter_passages([p], SEVERANCE)
        self.assertEqual([r["severed_by"] for r in out["severed"]],
                         ["sev-0003"])
        self.assertEqual(rec_page_key(out), "sources/retired-page")

    def test_corrected_statement_survives(self):
        # The correction itself, in its own words, is evidence —
        # it does not carry the severed claim's cues.
        p = passage("sources/import-policy",
                    "Each import is approved on its own card in "
                    "the console; the owner confirmed them one "
                    "by one.")
        out = severance.filter_passages([p], SEVERANCE)
        self.assertEqual(out["kept"], [p])
        self.assertEqual(out["severed"], [])
        self.assertFalse(out["all_evidence_severed"])

    def test_unsevered_passages_untouched_and_order_kept(self):
        ps = [passage("overview", "The wiki is canonical on its git remote."),
              passage("entities/owner", "The owner keeps the demo garden pages.")]
        out = severance.filter_passages(ps, SEVERANCE)
        self.assertEqual(out["kept"], ps)
        self.assertEqual(out["severed"], [])

    def test_absent_list_is_a_passthrough(self):
        ps = [passage("syntheses/decision-register",
                      "Collaborator's seat stays RESERVED.")]
        out = severance.filter_passages(ps, None)
        self.assertEqual(out["kept"], ps)
        self.assertFalse(out["all_evidence_severed"])
        self.assertIsNone(severance.load_severance(
            Path("/nonexistent/retrieval-severance.json")))


def rec_page_key(out):
    return out["severed"][0]["page"]


class PackEvidenceSeveranceTests(unittest.TestCase):
    def test_severed_recorded_not_packed_not_budget_dropped(self):
        dead = passage("syntheses/decision-register",
                       "Collaborator's seat stays RESERVED.", score=1.0)
        live = passage("syntheses/decision-register",
                       "The seat is open; Collaborator files on its own "
                       "branch.", score=0.8)
        result = evidence_packing.pack_evidence(
            [dead, live], severance=SEVERANCE)
        self.assertEqual([p["page"] for p in result["packed"]],
                         ["syntheses/decision-register"])
        self.assertEqual(result["packed"][0]["passage"],
                         live["passage"])
        self.assertEqual(len(result["severed"]), 1)
        cut = result["severed"][0]
        self.assertEqual(cut["reason"], "severed")
        self.assertEqual(cut["severed_by"], "sev-0001")
        self.assertEqual(cut["source"]["line"], 2)
        self.assertEqual(result["dropped"], [])
        self.assertFalse(result["all_evidence_severed"])

    def test_all_severed_flags_the_abstention_case(self):
        dead = passage("sources/x", "Collaborator's seat stays RESERVED.")
        result = evidence_packing.pack_evidence(
            [dead], severance=SEVERANCE)
        self.assertEqual(result["packed"], [])
        self.assertTrue(result["all_evidence_severed"])

    def test_no_severance_argument_keeps_legacy_shape(self):
        p = passage("syntheses/decision-register",
                    "Collaborator's seat stays RESERVED.")
        result = evidence_packing.pack_evidence([p])
        self.assertEqual(len(result["packed"]), 1)
        self.assertNotIn("severed", result)
        self.assertNotIn("all_evidence_severed", result)


if __name__ == "__main__":
    unittest.main()
