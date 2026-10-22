#!/usr/bin/env python3
"""Tests for scripts/wiki_pre_decision_challenge.py
(build-list wave 5: lesson injection + pre-decision
challenge — the challenge half).

Pins the contract on a FIXTURE repo in a temp dir:
  - overlap reuses the decision register's scoring: a
    proposal echoing a settled decision / rejected option
    / open thread ranks them, in the register's own order;
  - a proposal naming a rejected option's recorded match
    phrases is flagged as a re-proposal, with the reason
    the record gives for the loss;
  - the register-wide reproposal measurement is the
    decision checker's own line, verbatim;
  - lessons bearing on the proposal surface with their
    lifecycle state + gate posture; an unrelated proposal
    matches no lesson and flags nothing (honest zeros);
  - the pack is deterministic (two builds byte-identical
    as JSON) and advisory (exit 0 with findings present;
    exit 2 only for usage error / a missing register).

Run from the repo root:
    python3 -m unittest discover -s scripts/tests
No network.
"""

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

spec = importlib.util.spec_from_file_location(
    "wiki_pre_decision_challenge",
    SCRIPTS / "wiki_pre_decision_challenge.py")
challenge_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(challenge_mod)

spec = importlib.util.spec_from_file_location(
    "wiki_decision_records", SCRIPTS / "wiki_decision_records.py")
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

LEDGER = """# Corrections ledger (fixture)

## Entries

### 2026-09-01 — The phantom cache that does not exist

- **What was wrong:** a delivery claimed a cache existed;
  nothing in the product had been checked.
- **Standing rule:** never claim a cache exists unless it
  has been verified in the product itself.
- **Recorded:** [[cache-notes]]; `wiki/log.md`.

## Classification

| Entry | Class | Error kind | Standing rule |
|---|---|---|---|
| 2026-09-01 — The phantom cache that does not exist | correction | overstated-claim | verify-in-product |
"""

IDEAS = """# Ideas (fixture)

## Waiting for your call

- Adopt the two-level cache for the search door
- Repaint the fence

## Decided

- Nothing here.
"""

V1_LINE = {
    "kind": "decision", "id": "fx-d1",
    "title": "Cache shape for the search door",
    "status": "active", "decided": "2026-09-01",
    "redecided": None, "decided_by": "owner",
    "source": {"page": "wiki/syntheses/fixture.md",
               "section": "1"},
    "current_form": "One-level cache in front of the search door",
    "superseded_forms": [],
}

OVERLAY = {"decisions": {"fx-d1": {
    "tier": "not-recorded-at-the-time",
    "chosen": "One-level cache",
    "rejected": [{
        "option": "Two-level cache everywhere",
        "why_lost": "not-recorded-at-the-time",
        "recorded_rationale": None,
        "disposition": "rejected-at-decision",
        "match_phrases": ["two-level cache"],
    }],
    "reversibility": {"class": "reversible",
                      "grounding": "fixture record"},
    "outcome": {"status": "recorded", "text": "Shipped.",
                "source": "fixture"},
}}}

PROPOSAL = ("Adopt the two-level cache — after all, the "
            "cache exists in the product already")


def fixture_root(base: Path) -> Path:
    root = base / "fixture-wiki"
    (root / "wiki" / "rules").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "tools" / "ask").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "wiki" / "rules" / "corrections-ledger.md").write_text(
        LEDGER, encoding="utf-8")
    (root / "wiki" / "ideas.md").write_text(IDEAS, encoding="utf-8")
    for name in ("wiki_corrections.py",
                 "wiki_corrections_lifecycle.py",
                 "wiki_decision_records.py",
                 "wiki_pre_decision_challenge.py"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    shutil.copy(ROOT / "tools" / "ask" / "lessons.py",
                root / "tools" / "ask" / "lessons.py")
    (root / "evaluation" / "decisions-register.jsonl").write_text(
        json.dumps(V1_LINE) + "\n", encoding="utf-8")
    (root / "evaluation" / "decision-records-overlay.json").write_text(
        json.dumps(OVERLAY), encoding="utf-8")
    (root / "evaluation" / "decision-basis.json").write_text(
        json.dumps({"decisions": []}), encoding="utf-8")
    dr.build(root)
    return root


class ChallengeFixtureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = fixture_root(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def pack(self, text=PROPOSAL):
        return challenge_mod.build_challenge(
            self.root, text, "2026-09-03")

    def test_reproposal_flagged_with_loss_reason(self):
        flags = self.pack()["reproposal"]["proposal_flags"]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["decision"], "fx-d1")
        self.assertEqual(flags[0]["phrases"], ["two-level cache"])
        self.assertEqual(flags[0]["why_lost"],
                         "not-recorded-at-the-time")

    def test_board_measurement_is_the_checkers_own_line(self):
        # The fixture board's waiting bullet itself proposes
        # the two-level cache, so the checker's own
        # measurement counts it: 1 of 1, with the candidate
        # line naming fx-d1 — quoted verbatim, not recomputed.
        repro = self.pack()["reproposal"]
        self.assertTrue(repro["measured"].startswith(
            "1 of 1 rejected options"))
        self.assertEqual(len(repro["board_candidates"]), 1)
        self.assertIn("fx-d1", repro["board_candidates"][0])

    def test_overlap_ranks_rejected_option_and_open_thread(self):
        kinds = [(r["kind"], r["id"]) for r in self.pack()["overlap"]]
        self.assertIn(("REJECTED OPTION", "fx-d1"), kinds)
        self.assertIn(("OPEN THREAD", "0000"), kinds)
        scores = [r["score"] for r in self.pack()["overlap"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_lesson_surfaces_with_state_and_gate(self):
        matched = self.pack()["lessons"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["rule"], "verify-in-product")
        self.assertEqual(matched[0]["state"], "acted-on")
        self.assertEqual(matched[0]["gate"], "warning")

    def test_unrelated_proposal_is_an_honest_zero(self):
        pack = self.pack("Repaint the fence on Saturday")
        self.assertEqual(pack["reproposal"]["proposal_flags"], [])
        self.assertEqual(pack["lessons"], [])
        self.assertEqual(pack["lessons_considered"], 1)
        self.assertEqual(pack["open_threads_considered"], 2)

    def test_pack_is_deterministic(self):
        a = json.dumps(self.pack(), sort_keys=True, ensure_ascii=False)
        b = json.dumps(self.pack(), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)

    def test_render_names_the_flag_and_the_lesson(self):
        text = challenge_mod.render_text(self.pack())
        self.assertIn("advisory only", text)
        self.assertIn("re-proposes phrases of fx-d1", text)
        self.assertIn("The phantom cache that does not exist", text)
        self.assertIn("never claim a cache exists", text)

    def test_missing_register_is_a_named_door(self):
        with self.assertRaises(FileNotFoundError):
            challenge_mod.build_challenge(
                self.root / "no-such-tree", PROPOSAL, "2026-09-03")


class ChallengeCliTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = fixture_root(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_cli_advisory_exit_zero_despite_findings(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = challenge_mod.main(
                ["challenge", "--root", str(self.root),
                 "--today", "2026-09-03", "--text", PROPOSAL])
        self.assertEqual(rc, 0)
        self.assertIn("Pre-decision challenge", out.getvalue())

    def test_cli_json_is_parseable_and_stable(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = challenge_mod.main(
                ["challenge", "--root", str(self.root),
                 "--today", "2026-09-03", "--json",
                 "--text", PROPOSAL])
        self.assertEqual(rc, 0)
        pack = json.loads(out.getvalue())
        self.assertEqual(pack["kind"], "pre-decision-challenge")
        self.assertTrue(pack["advisory"])

    def test_cli_usage_error_exit_two(self):
        self.assertEqual(challenge_mod.main(["challenge"]), 2)


if __name__ == "__main__":
    unittest.main()
