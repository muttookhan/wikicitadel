"""Tests for tools/ask/provenance.py (W3 answer provenance pack).

Pins: the envelope is built from answer-time pipeline state
(the record, a real pack_evidence result, supplied retrieval
diagnostics) and never re-searches; each citation carries its
document identity (sha256 of the actual page file, DOI from
frontmatter where present), its retrieval/rerank/governance/
packing path, and its sentence links with character-exact
spans; the policy snapshot names the corpus state (git HEAD,
governance state hash, frozen tau) read from the artefacts
themselves; a zero-result abstention names its absent terms
and shows its scores against the threshold; a declared
model-knowledge fallback is labelled loudly; pickup stamps
the envelope additively and records/proposals without it are
unchanged in shape.

No tempfile (the suite must also run where tempdirs are
refused): fixtures are the shipped Ask fixtures and the real
wiki tree, read-only.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network.
"""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
WIKI = ROOT / "wiki"
FIXTURES = ASK_DIR / "tests" / "fixtures"

sys.path.insert(0, str(ASK_DIR))

import evidence_packing  # noqa: E402
import pickup  # noqa: E402
import provenance  # noqa: E402

ANSWERED_AT = "2026-10-22T01:30:00Z"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def scored_record():
    payload = load_fixture("sample_scored_answer.json")
    return pickup.build_qa_record(
        payload["question_entry"], payload["answer"],
        payload["citations"], ANSWERED_AT,
        question_type=payload.get("question_type"),
        mode=payload.get("mode"),
        citation_details=payload.get("citation_details"),
        sub_answers=payload.get("sub_answers"),
    )


def pack_for(record):
    passages = [dict(d) for d in record["citation_details"]]
    return evidence_packing.pack_evidence(passages, budget=6000)


def retrieval():
    return {
        "reranker": "coverage",
        "terms": [
            {"term": "memory", "documents": 9},
            {"term": "decisions", "documents": 21},
            {"term": "lease", "documents": 0},
        ],
        "candidates": [
            {"page": "overview", "rank": 1, "score": 4.21,
             "detail": {"reranker": "coverage",
                        "rerank_relevance": 0.91, "rerank": 1.14}},
            {"page": "syntheses/decision-register", "rank": 2,
             "score": 3.87,
             "detail": {"reranker": "coverage",
                        "rerank_relevance": 0.83, "rerank": 1.09}},
        ],
        "top_score": 4.21,
    }


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.record = scored_record()
        self.env = provenance.build_provenance(
            self.record, pack_result=pack_for(self.record),
            retrieval=retrieval(), wiki_dir=WIKI, root=ROOT)

    def test_envelope_identity_and_timestamp(self):
        self.assertEqual(self.env["kind"], "ask-provenance")
        self.assertEqual(self.env["version"], 1)
        self.assertEqual(self.env["question_id"], "q_fixture0002")
        self.assertEqual(self.env["assembled_at"], ANSWERED_AT)
        self.assertEqual(self.env["mode"], "deep-research")

    def test_source_type_is_local_corpus(self):
        st = self.env["source_type"]
        self.assertEqual(st["kind"], "local-corpus")
        self.assertIn("LOCAL CORPUS", st["label"])

    def test_policy_snapshot_reads_the_artefacts(self):
        snap = self.env["policy_snapshot"]
        artefact = json.loads(
            (ROOT / "evaluation/retrieval-governance.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(snap["governance_state_hash"],
                         artefact["state_hash"])
        self.assertEqual(snap["governance_inputs"],
                         artefact["generated_from"]["inputs"])
        baseline = json.loads(
            (ROOT / "evaluation/extended-baseline.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(snap["abstain_threshold"],
                         baseline["abstain_threshold"])
        self.assertEqual(snap["reranker"], "coverage")
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True)
        if out.returncode == 0:
            self.assertEqual(snap["git_head"], out.stdout.strip())

    def test_citation_document_identity_is_the_real_file(self):
        by_page = {c["page"]: c for c in self.env["citations"]}
        self.assertEqual(set(by_page), {"overview",
                                        "syntheses/decision-register"})
        doc = by_page["overview"]["document"]
        data = (WIKI / "overview.md").read_bytes()
        self.assertEqual(doc["sha256"],
                         hashlib.sha256(data).hexdigest())
        self.assertEqual(doc["bytes"], len(data))
        self.assertEqual(doc["path"], "wiki/overview.md")
        self.assertIn("doi", doc)  # present-or-null, never invented

    def test_citation_path_carries_every_stage(self):
        by_page = {c["page"]: c for c in self.env["citations"]}
        path = by_page["overview"]["path"]
        self.assertEqual(path["retrieval_rank"], 1)
        self.assertEqual(path["retrieval_score"], 4.21)
        self.assertEqual(path["rerank"]["reranker"], "coverage")
        self.assertEqual(path["rerank"]["relevance"], 0.91)
        self.assertEqual(path["packing"]["decision"], "packed")
        self.assertEqual(path["answer_score"], 0.9)
        self.assertIn("retrieval", path["surfaced_by"])
        self.assertIn("packing", path["surfaced_by"])

    def test_sentence_links_with_spans(self):
        linked = [
            (c["page"], link)
            for c in self.env["citations"]
            for link in c["sentences"]
        ]
        self.assertTrue(linked)
        supported = [
            (p, l) for p, l in linked
            if l["verdict"] in ("supported", "partially-supported")
        ]
        self.assertTrue(supported)
        spanned = [l for _p, l in supported if "span" in l]
        self.assertTrue(spanned)
        span = spanned[0]["span"]
        self.assertLess(span["start"], span["end"])
        summary = sum(
            c["support_summary"]["sentences"]
            for c in self.env["citations"])
        self.assertEqual(summary, len(linked))

    def test_absent_terms_named(self):
        self.assertEqual(self.env["absent_terms"], ["lease"])
        self.assertEqual(len(self.env["term_documents"]), 3)

    def test_verify_block_names_runnable_checks(self):
        commands = [c["command"]
                    for c in self.env["verify"]["checks"]]
        self.assertTrue(any(
            cmd.startswith("sha256sum")
            and "wiki/overview.md" in cmd for cmd in commands))
        self.assertTrue(any("wiki_cite_lock.py check" in cmd
                            for cmd in commands))
        self.assertTrue(any("pickup.py validate" in cmd
                            for cmd in commands))
        self.assertTrue(self.env["verify"]["instructions"])

    def test_build_is_deterministic(self):
        again = provenance.build_provenance(
            self.record, pack_result=pack_for(self.record),
            retrieval=retrieval(), wiki_dir=WIKI, root=ROOT)
        self.assertEqual(again, self.env)


class AbstentionEnvelopeTests(unittest.TestCase):
    def setUp(self):
        payload = load_fixture("sample_abstention.json")
        self.record = pickup.build_qa_record(
            payload["question_entry"], payload["answer"], [],
            ANSWERED_AT,
            question_type=payload.get("question_type"),
            abstention_reason=payload.get("abstention_reason"))
        self.env = provenance.build_provenance(
            self.record,
            retrieval={
                "terms": [{"term": "office", "documents": 3},
                          {"term": "lease", "documents": 0},
                          {"term": "renewal", "documents": 0}],
                "zero_result": True, "top_score": 0.42},
            wiki_dir=WIKI, root=ROOT)

    def test_abstention_shows_why(self):
        st = self.env["source_type"]
        self.assertEqual(st["kind"], "abstention")
        self.assertIn("ABSTENTION", st["label"])
        self.assertEqual(self.env["citations"], [])
        self.assertEqual(self.env["absent_terms"],
                         ["lease", "renewal"])
        self.assertTrue(self.env["zero_result"])
        abst = self.env["abstention"]
        self.assertIn("office lease", abst["reason"])
        self.assertEqual(abst["top_score"], 0.42)
        baseline = json.loads(
            (ROOT / "evaluation/extended-baseline.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(abst["tau"],
                         baseline["abstain_threshold"])
        self.assertLess(abst["top_score"], abst["tau"])
        self.assertFalse(abst["all_evidence_severed"])


class WithheldTests(unittest.TestCase):
    def test_severed_and_governance_withheld_are_named(self):
        record = scored_record()
        pack = pack_for(record)
        pack["severed"] = [{
            "page": "sources/old-form", "passage": "Dead.",
            "score": 0.8, "tokens": 2, "reason": "severed",
            "severed_by": "sev-0001",
            "source": "evaluation/retrieval-severance.json",
        }]
        pack["all_evidence_severed"] = False
        env = provenance.build_provenance(
            record, pack_result=pack,
            retrieval={"governance": [{
                "page": "sources/old-form", "state": "superseded",
                "outcome": "withheld",
                "reasons": ["superseded form"]}]},
            wiki_dir=WIKI, root=ROOT)
        kinds = {(w["page"], w["reason"])
                 for w in env["withheld"]}
        self.assertIn(("sources/old-form", "severed"), kinds)
        self.assertIn(("sources/old-form", "governance-withheld"),
                      kinds)
        severed = [w for w in env["withheld"]
                   if w["reason"] == "severed"][0]
        self.assertEqual(severed["severed_by"], "sev-0001")


class FallbackLabelTests(unittest.TestCase):
    def test_model_knowledge_fallback_is_labelled_loudly(self):
        env = provenance.build_provenance(
            scored_record(),
            retrieval={"fallback": {
                "kind": "model-knowledge", "local_recall": 0.31,
                "threshold": 0.5}})
        st = env["source_type"]
        self.assertEqual(st["kind"], "model-knowledge-fallback")
        self.assertIn("MODEL KNOWLEDGE", st["label"])
        self.assertEqual(st["local_recall"], 0.31)
        self.assertEqual(st["recall_threshold"], 0.5)


class BareBuildTests(unittest.TestCase):
    def test_no_tree_no_inputs_still_honest(self):
        env = provenance.build_provenance(scored_record())
        self.assertNotIn("policy_snapshot", env)
        for citation in env["citations"]:
            self.assertIsNone(citation["document"])
            self.assertEqual(citation["path"].get("answer_score"),
                             citation["path"].get("answer_score"))
        commands = [c["command"]
                    for c in env["verify"]["checks"]]
        self.assertFalse(any(cmd.startswith("sha256sum")
                             for cmd in commands))


class FrontmatterTests(unittest.TestCase):
    def test_doi_read_where_present_only(self):
        text = "---\ntitle: X\ndoi: 10.1000/xyz123\n---\nBody\n"
        self.assertEqual(
            provenance._frontmatter_value(text, "doi"),
            "10.1000/xyz123")
        self.assertIsNone(provenance._frontmatter_value(
            "---\ntitle: X\n---\nBody\n", "doi"))
        self.assertIsNone(provenance._frontmatter_value(
            "No frontmatter.\ndoi: 10.1/nope\n", "doi"))


class PickupSeamTests(unittest.TestCase):
    def test_stamp_only_when_supplied(self):
        entry = {"id": "q_p1", "question": "Q?"}
        plain = pickup.build_qa_record(entry, "A.", ["overview"],
                                       ANSWERED_AT)
        self.assertNotIn("provenance", plain)
        stamped = pickup.build_qa_record(
            entry, "A.", ["overview"], ANSWERED_AT,
            provenance={"kind": "ask-provenance", "version": 1})
        self.assertEqual(stamped["provenance"]["kind"],
                         "ask-provenance")

    def test_payload_variants(self):
        record = scored_record()
        self.assertIsNone(pickup._payload_provenance({}, record))
        given = {"kind": "ask-provenance", "version": 1}
        self.assertIs(
            pickup._payload_provenance(
                {"provenance": given}, record), given)
        built = pickup._payload_provenance(
            {"provenance_inputs": {"retrieval": retrieval(),
                                   "pack_result":
                                       pack_for(record)}},
            record)
        self.assertEqual(built["kind"], "ask-provenance")
        self.assertEqual(built["question_id"], "q_fixture0002")

    def test_proposal_section_only_with_envelope(self):
        record = scored_record()
        plain_md = pickup.stage_proposal_markdown(record)
        self.assertNotIn("## Provenance", plain_md)
        record["provenance"] = provenance.build_provenance(
            record, pack_result=pack_for(record),
            retrieval=retrieval(), wiki_dir=WIKI, root=ROOT)
        md = pickup.stage_proposal_markdown(record)
        self.assertIn("## Provenance", md)
        self.assertIn("LOCAL CORPUS", md)
        doc = [c for c in record["provenance"]["citations"]
               if c["page"] == "overview"][0]["document"]
        self.assertIn(doc["sha256"][:12], md)
        self.assertIn("Absent terms", md)


if __name__ == "__main__":
    unittest.main()
