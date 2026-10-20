#!/usr/bin/env python3
"""the build: query-log refinement loop (pattern: DeepRefine-Skill,
MIT). Dry-run proposals are evidence-labelled HIGH/MEDIUM/LOW by
deterministic rules; apply refuses LOW by default and stages the
rest at the gateway — never editing a wiki page.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gateway"))
spec = importlib.util.spec_from_file_location(
    "wiki_refine", ROOT / "scripts" / "wiki_refine.py")
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)
from gateway.config import Config  # noqa: E402
from gateway.store import GatewayStore  # noqa: E402


PAGE_A = """---
title: Alpha Page
type: concept
created: 2030-10-01
updated: 2030-10-01
sources: [raw/sources/a.md]
tags: [fixture]
---

Alpha body text about irrigation scheduling and soil moisture.
"""

PAGE_B = """---
title: Beta Page
type: concept
created: 2030-10-01
updated: 2030-10-01
sources: [raw/sources/b.md]
tags: [fixture]
---

Beta body text about compost and mulch.
"""


def make_root(tmp: Path) -> Path:
    (tmp / "wiki" / "access").mkdir(parents=True)
    (tmp / "wiki" / "concepts").mkdir(parents=True)
    (tmp / "wiki" / "queries").mkdir(parents=True)
    (tmp / "wiki" / "concepts" / "alpha.md").write_text(PAGE_A)
    (tmp / "wiki" / "concepts" / "beta.md").write_text(PAGE_B)
    return tmp


def qa_line(**kw) -> str:
    rec = {"id": "q_1", "question": "What is alpha?",
           "asker": "owner", "asked_at": "2030-10-10T10:00:00Z",
           "answered_at": "2030-10-10T10:05:00Z",
           "answer": "Alpha is the first letter. " * 30,
           "citations": ["concepts/alpha"], "status": "answered"}
    rec.update(kw)
    return json.dumps(rec)


def write_qa(root: Path, lines: list[str]) -> None:
    (root / "wiki" / "access" / "qa-2030.jsonl").write_text(
        "\n".join(lines) + "\n")


class FakeStore:
    """Records stage_proposal calls instead of writing staging files."""

    def __init__(self):
        self.calls = []

    def stage_proposal(self, **kw):
        self.calls.append(kw)
        return {"proposal_id": f"prop-fake{len(self.calls)}",
                "state": "draft"}


class TestLabels(unittest.TestCase):
    def test_stale_label_rules(self):
        material = {"commits": 2, "added": 30, "deleted": 5,
                    "lines": 35, "last": "2030-10-19"}
        modest = {"commits": 1, "added": 2, "deleted": 0,
                  "lines": 2, "last": "2030-10-15"}
        none = {"commits": 0, "added": 0, "deleted": 0,
                "lines": 0, "last": ""}
        self.assertEqual(rf.stale_label(material, False), "HIGH")
        self.assertEqual(rf.stale_label(modest, False), "MEDIUM")
        self.assertIsNone(rf.stale_label(none, False))
        # Git unavailable: frontmatter `updated` advancing is MEDIUM.
        self.assertEqual(rf.stale_label(None, True), "MEDIUM")
        self.assertIsNone(rf.stale_label(None, False))

    def test_material_threshold_boundary(self):
        at = {"commits": 1, "added": rf.MATERIAL_LINES, "deleted": 0,
              "lines": rf.MATERIAL_LINES, "last": "2030-10-19"}
        below = {"commits": 1, "added": rf.MATERIAL_LINES - 1,
                 "deleted": 0, "lines": rf.MATERIAL_LINES - 1,
                 "last": "2030-10-19"}
        self.assertEqual(rf.stale_label(at, False), "HIGH")
        self.assertEqual(rf.stale_label(below, False), "MEDIUM")


class TestDetectors(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))
        self.pages = rf.iter_pages(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stale_citation_material_is_high(self):
        write_qa(self.root, [qa_line()])
        records = rf.load_qa_records(self.root)

        def changes(rel, since):
            return {"commits": 1, "added": 40, "deleted": 2,
                    "lines": 42, "last": "2030-10-19"}

        out = rf.detect_stale_citations(records, self.pages, changes)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "HIGH")
        self.assertEqual(out[0]["target_path"], "wiki/concepts/alpha.md")

    def test_stale_citation_no_change_no_proposal(self):
        write_qa(self.root, [qa_line()])
        records = rf.load_qa_records(self.root)

        def changes(rel, since):
            return {"commits": 0, "added": 0, "deleted": 0,
                    "lines": 0, "last": ""}

        self.assertEqual(
            rf.detect_stale_citations(records, self.pages, changes), [])

    def test_repeat_cluster_medium_and_high_with_abstention(self):
        q = "How does irrigation scheduling work for soil moisture"
        write_qa(self.root, [
            qa_line(id="q_1", question=q),
            qa_line(id="q_2", question=q + " today",
                    citations=["concepts/beta"]),
        ])
        records = rf.load_qa_records(self.root)
        clusters = rf.cluster_questions(records)
        self.assertEqual(len(clusters), 1)
        out = rf.detect_gaps(records, self.pages, clusters)
        repeats = [p for p in out if p["kind"] == "gap-repeat"]
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0]["label"], "MEDIUM")

        write_qa(self.root, [
            qa_line(id="q_1", question=q),
            qa_line(id="q_2", question=q + " today",
                    abstained=True, abstention_reason="no source",
                    answer="", citations=[]),
        ])
        records = rf.load_qa_records(self.root)
        clusters = rf.cluster_questions(records)
        out = rf.detect_gaps(records, self.pages, clusters)
        repeats = [p for p in out if p["kind"] == "gap-repeat"]
        self.assertEqual(repeats[0]["label"], "HIGH")

    def test_single_abstention_is_high_gap(self):
        write_qa(self.root, [qa_line(
            id="q_9", question="What is the airspeed of a swallow",
            abstained=True, abstention_reason="not in the wiki",
            answer="", citations=[])])
        records = rf.load_qa_records(self.root)
        out = rf.detect_gaps(records, self.pages, [])
        gaps = [p for p in out if p["kind"] == "gap-abstained"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["label"], "HIGH")
        self.assertTrue(gaps[0]["new_page"])

    def test_thin_answer_rules(self):
        # Full-length, multi-citation, verdict-clean: not thin.
        good = {"answer": "x" * 400, "citations": ["a", "b"],
                "sub_answers": []}
        self.assertEqual(rf.thin_reasons(good), [])
        # Single citation alone, full length: not thin.
        one = {"answer": "x" * 400, "citations": ["a"],
               "sub_answers": []}
        self.assertEqual(rf.thin_reasons(one), [])
        # Hold verdict: thin.
        held = {"answer": "x" * 400, "citations": ["a", "b"],
                "trust_verdict": "hold", "sub_answers": []}
        self.assertIn("trust verdict hold", rf.thin_reasons(held))
        # Short + single citation: thin.
        short = {"answer": "brief", "citations": ["a"],
                 "sub_answers": []}
        self.assertTrue(rf.thin_reasons(short))

    def test_retrieved_never_cited_labels(self):
        write_qa(self.root, [
            qa_line(id="q_1", question="alpha question one"),
            qa_line(id="q_2", question="a different beta question",
                    citations=["concepts/beta"]),
        ])
        records = rf.load_qa_records(self.root)

        def ranker(question):
            # Beta ranks for both questions but is cited once (q_2);
            # alpha ranks for q_1 only and IS cited there. A third
            # page would be needed for a never-cited hit, so use
            # beta for q_1 only via a custom second fixture below.
            return ["wiki/concepts/beta.md"]

        out = rf.detect_retrieved_never_cited(
            records, self.pages, ranker)
        # beta is cited by q_2 -> excluded entirely.
        self.assertEqual(out, [])

    def test_retrieved_never_cited_low_and_medium(self):
        (self.root / "wiki" / "concepts" / "gamma.md").write_text(
            PAGE_B.replace("Beta Page", "Gamma Page"))
        self.pages = rf.iter_pages(self.root)
        write_qa(self.root, [
            qa_line(id="q_1", question="question one"),
            qa_line(id="q_2", question="question two",
                    citations=["concepts/beta"]),
        ])
        records = rf.load_qa_records(self.root)

        def ranker(question):
            if "one" in question:
                return ["wiki/concepts/gamma.md",
                        "wiki/concepts/alpha.md"]
            return ["wiki/concepts/gamma.md"]

        out = rf.detect_retrieved_never_cited(
            records, self.pages, ranker)
        gamma = [p for p in out
                 if p["target_path"] == "wiki/concepts/gamma.md"]
        self.assertEqual(len(gamma), 1)
        # Retrieved for 2 distinct questions, never cited -> MEDIUM.
        self.assertEqual(gamma[0]["label"], "MEDIUM")

        def ranker_one(question):
            return ["wiki/concepts/gamma.md"] if "one" in question else []

        out = rf.detect_retrieved_never_cited(
            records, self.pages, ranker_one)
        gamma = [p for p in out
                 if p["target_path"] == "wiki/concepts/gamma.md"]
        self.assertEqual(gamma[0]["label"], "LOW")

    def test_rich_citations_resolve(self):
        rec = {"citations": [{"page": "concepts/alpha", "score": 0.9,
                              "passage": "Alpha body"}],
               "sub_answers": [{"citations": ["concepts/beta"]}]}
        self.assertEqual(rf.record_citations(rec),
                         ["concepts/alpha", "concepts/beta"])
        self.assertEqual(
            rf.resolve_citation("concepts/alpha", self.pages),
            "wiki/concepts/alpha.md")
        self.assertEqual(rf.resolve_citation("alpha", self.pages),
                         "wiki/concepts/alpha.md")
        self.assertIsNone(rf.resolve_citation("nope", self.pages))


class TestApply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(Path(self._tmp.name))
        (self.root / "wiki" / "filings").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self):
        return {
            "date": "2030-10-20",
            "proposals": [
                {"id": "refine-x-high", "kind": "gap-abstained",
                 "label": "HIGH", "target_path": "wiki/concepts/alpha.md",
                 "section": "Refinement proposal", "sketch": "do it",
                 "evidence": {"question_id": "q_1"}, "new_page": False,
                 "status": "proposed", "proposal_id": None,
                 "apply_note": None},
                {"id": "refine-x-low", "kind": "retrieved-never-cited",
                 "label": "LOW", "target_path": "wiki/concepts/beta.md",
                 "section": "Refinement proposal", "sketch": "maybe",
                 "evidence": {"question_ids": ["q_1"]},
                 "new_page": False, "status": "proposed",
                 "proposal_id": None, "apply_note": None},
            ],
            "apply_runs": [],
        }

    def test_apply_refuses_low_by_default(self):
        manifest = self._manifest()
        rf.write_dry_run(self.root, {**manifest, "inputs": "x",
                                     "stats": {"qa_records": 0,
                                               "repeat_clusters": 0,
                                               "pages_scanned": 0,
                                               "proposals": 2,
                                               "by_label": {"HIGH": 1,
                                                            "MEDIUM": 0,
                                                            "LOW": 1},
                                               "by_kind": {}}})
        store = FakeStore()
        out = rf.apply_proposals(self.root, manifest, store=store)
        self.assertEqual(len(store.calls), 1)  # only HIGH staged
        by_id = {p["id"]: p for p in out["proposals"]}
        self.assertEqual(by_id["refine-x-high"]["status"], "staged")
        self.assertEqual(by_id["refine-x-low"]["status"], "refused")
        run = out["apply_runs"][-1]
        self.assertEqual(run["refused"], ["refine-x-low"])
        # The filing records the refusal.
        filing = (self.root / "wiki" / "filings"
                  / "refine-2030-10-20.md").read_text()
        self.assertIn("refused: refine-x-low", filing)

    def test_apply_include_low_stages_it_and_records_flag(self):
        manifest = self._manifest()
        rf.write_dry_run(self.root, {**manifest, "inputs": "x",
                                     "stats": {"qa_records": 0,
                                               "repeat_clusters": 0,
                                               "pages_scanned": 0,
                                               "proposals": 2,
                                               "by_label": {"HIGH": 1,
                                                            "MEDIUM": 0,
                                                            "LOW": 1},
                                               "by_kind": {}}})
        store = FakeStore()
        out = rf.apply_proposals(self.root, manifest,
                                 include_low=True, store=store)
        self.assertEqual(len(store.calls), 2)
        run = out["apply_runs"][-1]
        self.assertTrue(run["include_low"])
        self.assertEqual(run["refused"], [])

    def test_apply_with_real_gateway_stages_files(self):
        manifest = self._manifest()
        rf.write_dry_run(self.root, {**manifest, "inputs": "x",
                                     "stats": {"qa_records": 0,
                                               "repeat_clusters": 0,
                                               "pages_scanned": 0,
                                               "proposals": 2,
                                               "by_label": {"HIGH": 1,
                                                            "MEDIUM": 0,
                                                            "LOW": 1},
                                               "by_kind": {}}})
        env = {"GATEWAY_WIKI_ROOT": str(self.root),
               "GATEWAY_STAGING_DIR": str(self.root / "staging")}
        store = GatewayStore(Config(env=env))
        before = (self.root / "wiki" / "concepts"
                  / "alpha.md").read_text()
        out = rf.apply_proposals(self.root, manifest, store=store)
        staged = [p for p in out["proposals"]
                  if p["status"] == "staged"]
        self.assertEqual(len(staged), 1)
        pid = staged[0]["proposal_id"]
        self.assertTrue(
            (self.root / "staging" / "proposed" / f"{pid}.md").is_file())
        self.assertTrue(
            (self.root / "staging" / "proposed" / f"{pid}.json").is_file())
        # The wiki page itself is untouched — staging only.
        self.assertEqual(
            (self.root / "wiki" / "concepts" / "alpha.md").read_text(),
            before)


if __name__ == "__main__":
    unittest.main()
