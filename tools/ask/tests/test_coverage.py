"""Tests for the coverage-gap answer line (Marathon R2 lane B1;
gbrain pattern).

``tools/ask/coverage.py`` computes, from the searched result
set, what the corpus does NOT hold on the topic (searched
facets/communities with zero hits) plus the newest evidence
date among the packed passages. The line rides the answer
RECORD as a structured ``coverage`` field (via
``pickup.build_qa_record``) and the pickup report (the staged
proposal markdown) — never the answer text.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_coverage -v
or directly:
    python3 tools/ask/tests/test_coverage.py

No network is used.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import coverage  # noqa: E402
import pickup  # noqa: E402


PACKED = [
    {"page": "overview", "passage": "Older evidence.",
     "score": 0.9, "date": "2026-09-01"},
    {"page": "syntheses/register", "passage": "Newer evidence.",
     "score": 0.8, "updated": "2026-10-20T09:30:00Z"},
    {"page": "sources/note", "passage": "Undated evidence.",
     "score": 0.7},
]


class ComputeCoverageTests(unittest.TestCase):
    def test_empty_region_fixture_names_the_gap(self):
        # A fixture answer over an empty region: the leases
        # facet was searched and returned nothing at all.
        result = coverage.compute_coverage(
            [], searched=[{"name": "sources/leases", "hits": 0}]
        )
        self.assertEqual(result["gaps"], ["sources/leases"])
        self.assertIsNone(result["newest_evidence_date"])
        self.assertIn("sources/leases", result["line"])
        self.assertIn("no hits in sources/leases", result["line"])
        self.assertIn("no evidence was packed", result["line"])

    def test_fully_covered_fixture_has_no_gaps(self):
        result = coverage.compute_coverage(
            PACKED,
            searched=[
                {"name": "overview", "hits": 3},
                {"name": "syntheses", "hits": 1},
            ],
        )
        self.assertEqual(result["gaps"], [])
        self.assertIn("no gaps", result["line"])
        self.assertIn("2026-10-20", result["line"])

    def test_newest_evidence_date_is_the_max(self):
        self.assertEqual(
            coverage.newest_evidence_date(PACKED), "2026-10-20"
        )
        result = coverage.compute_coverage(PACKED, searched={})
        self.assertEqual(
            result["newest_evidence_date"], "2026-10-20"
        )

    def test_mapping_and_name_only_searched_forms(self):
        result = coverage.compute_coverage(
            PACKED, searched={"overview": 2, "sources/leases": 0}
        )
        self.assertEqual(result["gaps"], ["sources/leases"])
        # Name-only form: hits derive from the packed passages'
        # community fields — a searched community that packed
        # nothing is a gap.
        packed = [
            {"page": "a", "passage": "x", "community": "cluster-a",
             "date": "2026-10-01"},
        ]
        result = coverage.compute_coverage(
            packed, searched=["cluster-a", "cluster-b"]
        )
        self.assertEqual(result["gaps"], ["cluster-b"])

    def test_no_searched_information_claims_no_coverage(self):
        result = coverage.compute_coverage(PACKED)
        self.assertEqual(result["gaps"], [])
        self.assertIn(
            "no searched-facet information was recorded",
            result["line"],
        )

    def test_coverage_for_record_reads_citation_details(self):
        record = {
            "citation_details": [
                {"page": "overview", "score": 0.9,
                 "passage": "p", "date": "2026-08-15"},
                {"page": "syntheses/register", "score": 0.8,
                 "passage": "q", "date": "2026-10-05"},
            ]
        }
        result = coverage.coverage_for_record(
            record, searched=[{"facet": "leases", "hits": 0}]
        )
        self.assertEqual(result["gaps"], ["leases"])
        self.assertEqual(
            result["newest_evidence_date"], "2026-10-05"
        )


class CoverageOnTheRecordTests(unittest.TestCase):
    ENTRY = {
        "id": "q_cov0001", "question": "What about leases?",
        "asker": "owner@example.invalid",
        "asked_at": "2026-10-20T12:00:00Z", "status": "pending",
    }

    def test_record_stamps_coverage_only_when_supplied(self):
        cov = coverage.compute_coverage(
            [], searched=[{"name": "sources/leases", "hits": 0}]
        )
        record = pickup.build_qa_record(
            self.ENTRY, "An answer.", ["overview"],
            "2026-10-20T12:05:00Z", coverage=cov,
        )
        self.assertEqual(record["coverage"], cov)
        plain = pickup.build_qa_record(
            self.ENTRY, "An answer.", ["overview"],
            "2026-10-20T12:05:00Z",
        )
        self.assertNotIn("coverage", plain)
        # The answer text itself never gains the line.
        self.assertNotIn("Coverage:", record["answer"])

    def test_proposal_markdown_renders_the_coverage_line(self):
        cov = coverage.compute_coverage(
            PACKED, searched=[{"name": "sources/leases", "hits": 0}]
        )
        record = pickup.build_qa_record(
            self.ENTRY, "An answer.", ["overview"],
            "2026-10-20T12:05:00Z", coverage=cov,
        )
        markdown = pickup.stage_proposal_markdown(record)
        self.assertIn("## Coverage", markdown)
        self.assertIn(cov["line"], markdown)

    def test_payload_coverage_computed_from_searched_facets(self):
        payload = {
            "citation_details": [
                {"page": "overview", "score": 0.9,
                 "passage": "p", "date": "2026-10-11"},
            ],
            "searched_facets": [{"name": "leases", "hits": 0}],
        }
        cov = pickup._payload_coverage(payload)
        self.assertEqual(cov["gaps"], ["leases"])
        self.assertEqual(cov["newest_evidence_date"], "2026-10-11")
        self.assertIsNone(pickup._payload_coverage({}))

    def test_citation_detail_anchor_and_date_preserved(self):
        record = pickup.build_qa_record(
            self.ENTRY, "An answer.", ["overview"],
            "2026-10-20T12:05:00Z",
            citation_details=[{
                "page": "overview", "score": 0.9, "passage": "p",
                "anchor": "founding", "date": "2026-10-11",
            }],
        )
        detail = record["citation_details"][0]
        self.assertEqual(detail["anchor"], "founding")
        self.assertEqual(detail["date"], "2026-10-11")


if __name__ == "__main__":
    unittest.main()
