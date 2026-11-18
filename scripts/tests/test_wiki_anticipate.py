"""Tests for scripts/wiki_anticipate.py — the anticipatory
sweep (sleep-time compute).

A fixture wiki is built in a temp dir with the real
wiki_anticipate.py + wiki_search.py + wiki_validate.py
copied in, so every module's ROOT resolves to the fixture.
The fixture pins the behaviours the build was specified
for:

  * the briefing carries all six standing questions, with
    the standing answers quoted under the page's as-of
    stamp, and the live-query fence replaced by its note;
  * the fresh-evidence assembly really reads the
    artefacts: Ideas Waiting leads, the Ask log's pending
    question, the eval headline, the staged proposal count
    (prop-*.md only — qa-*.md artefacts are not proposals),
    the page's own prose-dated clocks for Q5, the log tail
    for Q6;
  * the packets: the six standing questions come first,
    every packet's pages exist in the fixture and number
    at most five, and the whole build is deterministic —
    two runs with the same date are byte-identical;
  * a wiki with no standing-question page is a clear
    error, never a fabricated briefing.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REAL_SCRIPTS = Path(__file__).resolve().parent.parent
SCRIPTS = ("wiki_anticipate", "wiki_search", "wiki_validate")

CURRENT_STATE = """---
title: Current state
type: synthesis
created: 2030-10-14
updated: 2030-10-19
sources: []
tags: [synthesis]
---

# Current state

**As of: 2030-10-19.**

## Q1. Where does everything stand, overall?

Everything is fixture-shaped and calm.

## Q2. What is blocked, and on whom?

One thing waits on the owner's tap.

## Q3. What decisions await the owner?

The queue in the brief.

## Q4. What is live right now?

The fixture Lens, and nothing else.

## Q5. What money clocks are ticking?

- **Mar 31, 2030** — the grant window closes.
- **Apr 25, 2030** — the credit expires.

## Q6. What changed most recently?

See the log.

```wiki-query
type = synthesis
```

## Refresh contract

Fixture.
"""

LOG = """# Log

## [2030-10-17] setup | Fixture stood up

The fixture wiki exists.

## [2030-10-18] build | Fixture Lens built

Built and verified.

## [2030-10-19] build | Fixture gateway staged

One proposal staged; the rest is blocked on nothing.
"""

IDEAS = """# Ideas

## Waiting for your call

- **Alpha idea** — the first waiting item, with detail.
- **Beta idea** — the second waiting item.

## Approved

- **Gamma idea** — already approved.
"""

QA = "\n".join([
    json.dumps({"id": "q_1", "status": "answered",
                "question": "What is the fixture for?",
                "answered_at": "2030-10-18T00:00:00Z",
                "abstained": False}),
    json.dumps({"id": "q_2", "status": "pending",
                "question": "Is the fixture calm?",
                "abstained": False}),
]) + "\n"

EVAL = json.dumps({
    "label": "extended-latest",
    "generated_at": "2030-10-19T00:00:00+00:00",
    "engine": "hybrid", "corpus_docs": 6,
    "aggregates": {"questions": 10,
                   "citation_coverage": {"@10": 0.9},
                   "hit_rate_topk": 0.9,
                   "mrr_must_cite": 0.8},
    "by_class": {"standard": {"citation_coverage":
                               {"@10": 0.95}},
                 "temporal": {"citation_coverage":
                              {"@10": 0.5}}}})

CASES = json.dumps({"kind": "case", "case_id": "case-0001",
                    "status": "open"}) + "\n"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_fixture(root, with_state=True):
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS:
        shutil.copy(REAL_SCRIPTS / f"{name}.py",
                    root / "scripts" / f"{name}.py")
    if with_state:
        _write(root / "wiki" / "syntheses" / "current-state.md",
               CURRENT_STATE)
    _write(root / "wiki" / "log.md", LOG)
    _write(root / "wiki" / "ideas.md", IDEAS)
    _write(root / "wiki" / "access" / "qa.jsonl", QA)
    _write(root / "wiki" / "overview.md",
           "# Overview\n\nThe fixture wiki at a glance: calm,"
           " staged, and waiting on one tap.\n")
    _write(root / "wiki" / "sources" / "fixture-source.md",
           "# Fixture source\n\nEvidence about the fixture:"
           " the grant window and the credit clock.\n")
    _write(root / "evaluation" / "results"
           / "extended-latest.json", EVAL)
    _write(root / "evaluation" / "contradiction-cases.jsonl",
           CASES)
    _write(root / "staging" / "proposed" / "prop-abc123.md",
           "# A staged proposal\n")
    _write(root / "staging" / "proposed" / "qa-q_9.md",
           "# A QA artefact, not a proposal\n")
    return root


def load_anticipate(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_anticipate_fixture",
        root / "scripts" / "wiki_anticipate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnticipateFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = build_fixture(Path(cls.tmp) / "repo")
        cls.ant = load_anticipate(cls.root)
        cls.md, cls.packets = cls.ant.build_briefing(
            cls.root, date(2030, 10, 20), 10)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestBriefing(AnticipateFixture):
    def test_all_six_questions_present(self):
        for n in range(1, 7):
            self.assertIn(f"### Q{n}.", self.md)

    def test_as_of_stamp_carried(self):
        self.assertIn("as of 2030-10-19", self.md)

    def test_honesty_header_present(self):
        self.assertIn("no prose answers were generated",
                      self.md)
        self.assertIn("retrieval packets", self.md)

    def test_live_query_fence_replaced_by_note(self):
        self.assertNotIn("```wiki-query", self.md)
        self.assertIn("Live-query table omitted", self.md)

    def test_waiting_leads_in_q3_evidence(self):
        self.assertIn("Alpha idea", self.md)
        self.assertIn("Beta idea", self.md)
        self.assertNotIn("- Gamma idea", self.md)
        self.assertIn("**2 item(s) waiting**", self.md)

    def test_staged_proposals_count_props_only(self):
        self.assertIn("Staged proposal files present", self.md)
        self.assertIn("**1**", self.md)
        self.assertIn("prop-abc123.md", self.md)

    def test_open_cases_counted(self):
        self.assertIn("Contradiction Cases open: **1**",
                      self.md)

    def test_pending_qa_question_in_q2_evidence(self):
        self.assertIn("Is the fixture calm?", self.md)

    def test_eval_headline_in_q1_evidence(self):
        self.assertIn("0.9", self.md)
        self.assertIn("temporal", self.md)

    def test_prose_clocks_extracted_for_q5(self):
        self.assertIn("Mar 31, 2030", self.md)
        self.assertIn("Apr 25, 2030", self.md)
        self.assertIn("Standing page's clock, verbatim",
                      self.md)

    def test_log_tail_in_q6_evidence(self):
        self.assertIn("Fixture gateway staged", self.md)


class TestPackets(AnticipateFixture):
    def test_standing_questions_come_first(self):
        first = [p["query"]
                 for p in self.packets["packets"][:6]]
        self.assertEqual(
            first[0], "Where does everything stand, overall?")
        self.assertTrue(
            all(p["predicted_from"] == "standing-question"
                for p in self.packets["packets"][:6]))

    def test_packets_capped_and_pages_exist(self):
        self.assertLessEqual(len(self.packets["packets"]), 10)
        for pack in self.packets["packets"]:
            self.assertLessEqual(len(pack["included"]), 5)
            for inc in pack["included"]:
                self.assertTrue(
                    (self.root / inc["path"]).is_file(),
                    inc["path"])

    def test_packets_json_round_trip(self):
        blob = json.dumps(self.packets)
        again = json.loads(blob)
        self.assertEqual(again["generated_for"], "2030-10-20")
        self.assertEqual(again["corpus_docs"],
                         self.packets["corpus_docs"])

    def test_deterministic(self):
        md2, packets2 = self.ant.build_briefing(
            self.root, date(2030, 10, 20), 10)
        self.assertEqual(self.md, md2)
        self.assertEqual(
            json.dumps(self.packets, sort_keys=True),
            json.dumps(packets2, sort_keys=True))


class TestMissingStateAndCli(unittest.TestCase):
    def test_missing_current_state_is_a_clear_error(self):
        tmp = tempfile.mkdtemp()
        try:
            root = build_fixture(Path(tmp) / "bare",
                                 with_state=False)
            ant = load_anticipate(root)
            with self.assertRaises(ValueError):
                ant.build_briefing(root, date(2030, 10, 20), 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_writes_both_artefacts(self):
        tmp = tempfile.mkdtemp()
        try:
            root = build_fixture(Path(tmp) / "repo")
            out = Path(tmp) / "out"
            proc = subprocess.run(
                [sys.executable,
                 str(root / "scripts" / "wiki_anticipate.py"),
                 "--date", "2030-10-20", "--out-dir", str(out)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(
                (out / "anticipated-2030-10-20.md").is_file())
            self.assertTrue(
                (out / "anticipated-2030-10-20-packets.json")
                .is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
