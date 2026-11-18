"""Tests for tools/ask/claim_grouping.py (W3 claim-grouped
citation presentation).

Pins: the grouping is READ from the record's own recorded
structure — the provenance envelope's answer-time sentence
links first, the sub-answer decomposition second — and never
re-derived from prose; a citation supporting several claims
appears under each, marked shared; a citation supporting no
single claim stays visible as unattached; a record with no
claim structure (and any abstention) renders byte-identically
to the pre-grouping proposal; an envelope naming another
record is not trusted; rendering is deterministic.

No tempfile (the suite must also run where tempdirs are
refused): fixtures are the shipped Ask fixtures and the real
wiki tree, read-only.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network.
"""

import json
import sys
import unittest
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
WIKI = ROOT / "wiki"
FIXTURES = ASK_DIR / "tests" / "fixtures"

sys.path.insert(0, str(ASK_DIR))

import claim_grouping  # noqa: E402
import evidence_packing  # noqa: E402
import pickup  # noqa: E402
import provenance  # noqa: E402

ANSWERED_AT = "2026-10-22T01:35:00Z"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def scored_record(with_envelope=False):
    payload = load_fixture("sample_scored_answer.json")
    record = pickup.build_qa_record(
        payload["question_entry"], payload["answer"],
        payload["citations"], ANSWERED_AT,
        question_type=payload.get("question_type"),
        mode=payload.get("mode"),
        citation_details=payload.get("citation_details"),
        sub_answers=payload.get("sub_answers"),
    )
    if with_envelope:
        pack = evidence_packing.pack_evidence(
            [dict(d) for d in record["citation_details"]],
            budget=6000)
        record["provenance"] = provenance.build_provenance(
            record, pack_result=pack, retrieval=None,
            wiki_dir=WIKI, root=ROOT)
    return record


def plain_record():
    """A single-part cited answer: no envelope, no
    decomposition — no claim structure exists to present."""
    entry = {"id": "q_plain0001", "question": "What is this?",
             "asker": "owner@example.com",
             "asked_at": "2026-10-20T12:00:00Z",
             "status": "pending"}
    return pickup.build_qa_record(
        entry, "It is the wiki overview page.", ["overview"],
        ANSWERED_AT,
        citation_details=[{
            "page": "overview", "score": 0.5,
            "passage": "This wiki exists because [[owner]] lost "
                       "three months of agent memory"}])


class ProvenanceGroupingTests(unittest.TestCase):
    def setUp(self):
        self.record = scored_record(with_envelope=True)
        self.grouping = claim_grouping.group_claims(self.record)

    def test_grouping_comes_from_the_envelope(self):
        self.assertIsNotNone(self.grouping)
        self.assertEqual(self.grouping["kind"], "ask-claim-groups")
        self.assertEqual(self.grouping["sources"], ["provenance"])
        units = [(g["unit"], g["source"])
                 for g in self.grouping["groups"]]
        self.assertEqual(units, [("answer", "provenance"),
                                 ("sub-answer", "provenance"),
                                 ("sub-answer", "provenance")])

    def test_top_level_claim_carries_both_citations(self):
        # The scorer's greedy union selected both passages for
        # the answer's single sentence (provenance's own links);
        # the group must show exactly those, no more.
        claim = self.grouping["groups"][0]["claims"][0]
        self.assertEqual(claim["verdict"], "partially-supported")
        self.assertEqual(
            [c["key"] for c in claim["citations"]],
            ["overview", "syntheses/decision-register"])

    def test_sub_answer_links_attributed_to_the_right_sub(self):
        # The envelope labels both sub-answers "sub-answer";
        # attribution is by the sub's own entry keys + the
        # recorded sentence text.
        subs = self.grouping["groups"][1:]
        self.assertEqual(
            [c["key"] for c in subs[0]["claims"][0]["citations"]],
            ["overview"])
        self.assertEqual(
            [c["key"] for c in subs[1]["claims"][0]["citations"]],
            ["syntheses/decision-register"])
        self.assertEqual(subs[0]["question"],
                         "Why does this wiki exist?")
        self.assertEqual(subs[1]["question"],
                         "Who decides things in this wiki?")

    def test_shared_citations_marked_on_every_occurrence(self):
        # Each citation supports the top-level claim AND one
        # sub-answer claim: shared, named once at the top.
        self.assertEqual(
            self.grouping["shared_keys"],
            ["overview", "syntheses/decision-register"])
        for group in self.grouping["groups"]:
            for claim in group["claims"]:
                for cite in claim["citations"]:
                    self.assertTrue(cite["shared"])

    def test_no_citation_lost_or_invented(self):
        grouped = set()
        for group in self.grouping["groups"]:
            for claim in group["claims"]:
                grouped.update(
                    c["key"] for c in claim["citations"])
            grouped.update(
                c["key"] for c in group["unattached_citations"])
        self.assertEqual(
            grouped, {"overview", "syntheses/decision-register"})

    def test_rendered_section_shape(self):
        md = pickup.stage_proposal_markdown(self.record)
        self.assertIn("## Claims and their evidence", md)
        grouped_at = md.index("## Claims and their evidence")
        flat_at = md.index("## Sources used")
        self.assertLess(grouped_at, flat_at)
        self.assertIn("**shared**", md)
        self.assertIn("partially-supported; coverage", md)

    def test_deterministic(self):
        again = scored_record(with_envelope=True)
        self.assertEqual(
            claim_grouping.group_claims(self.record),
            claim_grouping.group_claims(again))
        self.assertEqual(
            pickup.stage_proposal_markdown(self.record),
            pickup.stage_proposal_markdown(again))


class SubAnswerGroupingTests(unittest.TestCase):
    def setUp(self):
        self.record = scored_record(with_envelope=False)
        self.grouping = claim_grouping.group_claims(self.record)

    def test_groups_come_from_the_decomposition(self):
        self.assertEqual(self.grouping["sources"], ["sub-answers"])
        groups = self.grouping["groups"]
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertEqual(group["unit"], "sub-answer")
            self.assertEqual(len(group["claims"]), 1)
            # No sentence verdicts were recorded on this path:
            # absent, never synthesised.
            self.assertIsNone(group["claims"][0]["verdict"])
            self.assertIsNone(group["claims"][0]["coverage"])

    def test_rendering_states_the_basis(self):
        md = pickup.stage_proposal_markdown(self.record)
        self.assertIn("## Claims and their evidence", md)
        self.assertIn("Grouped by sub-answer", md)

    def test_top_level_citations_covered_by_subs_add_no_group(self):
        units = [g["unit"] for g in self.grouping["groups"]]
        self.assertNotIn("answer", units)


class FallbackTests(unittest.TestCase):
    def test_plain_record_has_no_grouping(self):
        record = plain_record()
        self.assertIsNone(claim_grouping.group_claims(record))
        self.assertIsNone(
            claim_grouping.render_claim_groups(record))

    def test_plain_record_proposal_is_the_flat_form(self):
        record = plain_record()
        md = pickup.stage_proposal_markdown(record)
        self.assertNotIn("## Claims and their evidence", md)
        self.assertIn("## Sources used", md)
        self.assertIn("- [[overview]] — relevance 0.5", md)

    def test_abstention_never_groups(self):
        payload = load_fixture("sample_abstention.json")
        record = pickup.build_qa_record(
            payload["question_entry"], payload["answer"],
            payload.get("citations") or [], ANSWERED_AT,
            abstention_reason=payload.get("abstention_reason"))
        self.assertIsNone(claim_grouping.group_claims(record))
        md = pickup.stage_proposal_markdown(record)
        self.assertNotIn("## Claims and their evidence", md)
        self.assertIn("## Abstention", md)

    def test_mismatched_envelope_is_not_trusted(self):
        record = scored_record(with_envelope=True)
        record["provenance"] = dict(record["provenance"])
        record["provenance"]["question_id"] = "q_someone_else"
        grouping = claim_grouping.group_claims(record)
        self.assertEqual(grouping["sources"], ["sub-answers"])

    def test_non_dict_and_empty_records(self):
        self.assertIsNone(claim_grouping.group_claims(None))
        self.assertIsNone(claim_grouping.group_claims({}))
        self.assertIsNone(claim_grouping.render_claim_groups({}))


class SyntheticEnvelopeTests(unittest.TestCase):
    """Hand-built envelopes pin the construction rules the
    fixture cannot reach: an unsupported sentence, a citation
    selected for nothing, and a citation shared by two claims
    of the SAME unit."""

    def record(self):
        entry = {"id": "q_synth0001", "question": "Synthetic?",
                 "asker": "owner@example.com",
                 "asked_at": "2026-10-20T12:00:00Z",
                 "status": "pending"}
        answer = ("The overview page describes the reset. "
                  "The lease terms are generous and fair.")
        record = pickup.build_qa_record(
            entry, answer, ["overview"], ANSWERED_AT,
            citation_details=[{
                "page": "overview", "score": 0.7,
                "passage": "lost three months of agent memory"}])
        record["provenance"] = {
            "kind": "ask-provenance",
            "version": 1,
            "question_id": "q_synth0001",
            "citations": [{
                "page": "overview", "key": "overview",
                "passage": "lost three months of agent memory",
                "sentences": [{
                    "unit": "answer", "index": 0,
                    "sentence": "The overview page describes "
                                "the reset.",
                    "verdict": "supported", "coverage": 0.9,
                }],
            }],
        }
        return record

    def test_unsupported_sentence_shows_with_no_citation(self):
        grouping = claim_grouping.group_claims(self.record())
        claims = grouping["groups"][0]["claims"]
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0]["verdict"], "supported")
        self.assertEqual(
            [c["key"] for c in claims[0]["citations"]],
            ["overview"])
        self.assertEqual(claims[1]["verdict"], "unsupported")
        self.assertEqual(claims[1]["citations"], [])
        md = pickup.stage_proposal_markdown(self.record())
        self.assertIn("scored unsupported at answer time", md)

    def test_citation_selected_for_nothing_is_unattached(self):
        record = self.record()
        record["provenance"]["citations"][0]["sentences"] = []
        grouping = claim_grouping.group_claims(record)
        group = grouping["groups"][0]
        self.assertEqual(
            [c["key"] for c in group["unattached_citations"]],
            ["overview"])
        md = pickup.stage_proposal_markdown(record)
        self.assertIn("supporting no single claim", md)


if __name__ == "__main__":
    unittest.main()
