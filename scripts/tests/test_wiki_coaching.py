#!/usr/bin/env python3
"""Item 41: gates coach, don't only reject.

For each surface, two properties are pinned:
  - the coaching text renders (what failed, why it matters,
    the concrete change that would pass), derived from the
    surface's own inputs;
  - the VERDICT is unchanged: gate exit codes, refine's
    staged/refused split, and the lanes' counts are exactly
    what the pre-coaching machinery produced.

Surfaces: (a) wiki_decision_gate's premortem line,
(b) wiki_refine's LOW refusals, (c) wiki_lint_lanes'
filing. (The gateway eval gate's guidance is tested in
tools/gateway/tests/test_evalgate.py.)

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gateway"))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("wiki_decision_gate")
rf = _load("wiki_refine")
lanes = _load("wiki_lint_lanes")

WRITTEN = """# Prop

## Premortem (2030-10-20)

It is 2027-04-20 and this failed. The reasons were:

1. Something concrete went wrong. — Mitigation: named.
"""

PLACEHOLDER = """# Prop

---

## Premortem (not yet written)

**NOT YET WRITTEN.** Before this proposal is put to the
owner, a separate pass replaces this placeholder.
"""

BARE = "# Prop\n\nNothing here.\n"


class FakeStore:
    def __init__(self):
        self.calls = []

    def stage_proposal(self, **kw):
        self.calls.append(kw)
        return {"proposal_id": f"prop-fake{len(self.calls)}",
                "state": "draft"}


# -- (a) decision gate --------------------------------------------------------

class TestGateCoaching(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        pdir = self.root / "staging" / "proposed"
        pdir.mkdir(parents=True)
        (pdir / "prop-bare.md").write_text(BARE)
        (pdir / "prop-ph.md").write_text(PLACEHOLDER)
        (pdir / "prop-ok.md").write_text(WRITTEN)

    def tearDown(self):
        self._tmp.cleanup()

    def test_gap_states_distinguished(self):
        self.assertEqual(gate.premortem_gap(WRITTEN), "written")
        self.assertEqual(gate.premortem_gap(PLACEHOLDER),
                         "placeholder")
        self.assertEqual(gate.premortem_gap(BARE), "none")

    def test_coaching_names_missing_and_template(self):
        rows = {pid: (gap, text) for pid, gap, text
                in gate.premortem_coaching(self.root)}
        self.assertEqual(set(rows), {"prop-bare", "prop-ph"})
        self.assertEqual(rows["prop-bare"][0], "none")
        self.assertIn("no premortem block at all",
                      rows["prop-bare"][1])
        self.assertEqual(rows["prop-ph"][0], "placeholder")
        self.assertIn("NOT YET WRITTEN", rows["prop-ph"][1])
        for _gap, text in rows.values():
            self.assertIn("templates/proposal.md", text)
            self.assertIn("## Premortem (YYYY-MM-DD)", text)

    def _run_main(self, scan_result):
        real_status = gate.premortem_status
        real_coaching = gate.premortem_coaching
        with mock.patch.object(gate, "scan",
                               lambda: scan_result), \
             mock.patch.object(
                 gate, "premortem_status",
                 lambda: real_status(self.root)), \
             mock.patch.object(
                 gate, "premortem_coaching",
                 lambda: real_coaching(self.root)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = gate.main(["gate"])
            return code, buf.getvalue()

    def test_coaching_prints_and_verdict_unchanged(self):
        empty = {"hits": [], "forms": [], "files_scanned": 0}
        code, out = self._run_main(empty)
        # No LIVE hits -> exit 0, exactly as before coaching;
        # the missing premortems are surfaced, with coaching.
        self.assertEqual(code, 0)
        self.assertIn("missing a written premortem", out)
        self.assertIn("coaching:", out)
        self.assertIn("templates/proposal.md", out)

    def test_live_hit_still_blocks_despite_coaching(self):
        live = {"hits": [{
                    "classification": "LIVE", "file": "wiki/x.md",
                    "line": 1, "form_id": "f1", "matched": "phrase: p",
                    "reason": "r", "excerpt": "e",
                    "form_title": "Form"}],
                "forms": [{"form_id": "f1"}], "files_scanned": 1}
        code, out = self._run_main(live)
        self.assertEqual(code, 1)
        self.assertIn("coaching:", out)


# -- (b) refine refusals ------------------------------------------------------

class TestRefineCoaching(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        (self.root / "wiki" / "filings").mkdir(parents=True)
        (self.root / "wiki" / "concepts" / "alpha.md").write_text(
            "# Alpha\n")
        (self.root / "wiki" / "concepts" / "beta.md").write_text(
            "# Beta\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self):
        return {
            "date": "2030-10-20",
            "proposals": [
                {"id": "refine-x-high", "kind": "gap-abstained",
                 "label": "HIGH",
                 "target_path": "wiki/concepts/alpha.md",
                 "section": "Refinement proposal", "sketch": "do it",
                 "evidence": {"question_id": "q_1"},
                 "new_page": False, "status": "proposed",
                 "proposal_id": None, "apply_note": None,
                 "coaching_note": None},
                {"id": "refine-x-low", "kind": "retrieved-never-cited",
                 "label": "LOW",
                 "target_path": "wiki/concepts/beta.md",
                 "section": "Refinement proposal", "sketch": "maybe",
                 "evidence": {"question_ids": ["q_7"],
                              "questions": ["beta question"],
                              "retrieved_for": 1},
                 "new_page": False, "status": "proposed",
                 "proposal_id": None, "apply_note": None,
                 "coaching_note": None},
            ],
            "apply_runs": [],
        }

    def _dry(self, manifest):
        rf.write_dry_run(self.root, {**manifest, "inputs": "x",
                                     "stats": {
                                         "qa_records": 0,
                                         "repeat_clusters": 0,
                                         "pages_scanned": 0,
                                         "proposals": 2,
                                         "by_label": {"HIGH": 1,
                                                      "MEDIUM": 0,
                                                      "LOW": 1},
                                         "by_kind": {}}})

    def test_note_is_written_from_scoring_inputs(self):
        note = rf.low_coaching_note(self._manifest()["proposals"][1])
        self.assertIn("wiki/concepts/beta.md", note)
        self.assertIn("q_7", note)
        self.assertIn("SECOND distinct", note)
        self.assertIn("--include-low", note)

    def test_refusal_carries_note_and_verdict_unchanged(self):
        manifest = self._manifest()
        self._dry(manifest)
        store = FakeStore()
        out = rf.apply_proposals(self.root, manifest, store=store)
        # Verdict identical to the pre-coaching loop: HIGH staged,
        # LOW refused, run lists the same ids.
        self.assertEqual(len(store.calls), 1)
        run = out["apply_runs"][-1]
        self.assertEqual(run["refused"], ["refine-x-low"])
        by_id = {p["id"]: p for p in out["proposals"]}
        self.assertEqual(by_id["refine-x-low"]["status"], "refused")
        note = by_id["refine-x-low"]["coaching_note"]
        self.assertTrue(note)
        self.assertIn("SECOND distinct", note)
        self.assertIsNone(by_id["refine-x-high"]["coaching_note"])
        # The filing records the refusal AND its coaching.
        filing = (self.root / "wiki" / "filings"
                  / "refine-2030-10-20.md").read_text()
        self.assertIn("refused: refine-x-low", filing)
        self.assertIn("coaching for refine-x-low", filing)

    def test_include_low_still_stages(self):
        manifest = self._manifest()
        self._dry(manifest)
        store = FakeStore()
        out = rf.apply_proposals(self.root, manifest,
                                 include_low=True, store=store)
        self.assertEqual(len(store.calls), 2)
        self.assertEqual(out["apply_runs"][-1]["refused"], [])


# -- (c) lint lanes filing ------------------------------------------------------

def _lanes_with_findings():
    empty_lane = {"count": 0, "top": None, "pages_scanned": 0,
                  "statements": 0, "cases_open": 0}
    l1 = {**empty_lane, "count": 1, "cases_open": 1,
          "top": {"pages": 2, "page": "wiki/a.md",
                  "statement": "A fact told two ways."}}
    l2 = {"count": 0, "oldest": [], "scanned": 3, "undated": 0,
          "cutoff": "2030-09-20",
          "semantic": [{"page": "wiki/old.md",
                        "signal": "status superseded",
                        "detail": "superseded_by wiki/new.md"}],
          "semantic_count": 1, "claim_pages": 0,
          "outcomes_recorded": 0, "talk_pages": 0,
          "attested_current": 0,
          "attestation_expired": [
              {"page": "wiki/att.md", "verified_until": "2030-01-01",
               "verified_by": "owner"}],
          "attestation_expired_count": 1,
          "attestation_invalid": [],
          "reverify_due": [
              {"page": "wiki/claims/c.md", "due": "2030-10-01",
               "status": "overdue", "days_overdue": 19,
               "last_verified": "2030-09-01", "verifications": 2}],
          "reverify_due_count": 1}
    l3 = {"broken_count": 1, "broken": ["wiki/a.md -> [[nope]]"],
          "orphan_count": 1, "orphans": ["wiki/lonely.md"],
          "validator_exit": 0}
    l4 = {"new_total": 1, "baselined_total": 0, "verdict": "findings",
          "baseline_present": True,
          "surfaces": [{"surface": "lens", "location": "/tmp/x",
                        "present": True, "files_scanned": 4,
                        "new_total": 1, "baselined_total": 0,
                        "verdict": "findings",
                        "findings": [{"file": "a.txt",
                                      "pattern": "credit-card",
                                      "new_count": 1,
                                      "baselined_count": 0}]}]}
    l5 = {"checked": 1, "pages": 1, "verified": 0,
          "divergences": [{"page": "wiki/a.md", "page_line": 3,
                           "quote": "quoted words",
                           "divergence": "word 2 differs"}],
          "caveats": {"checked": 1, "carried": 0,
                      "findings": [{"page": "wiki/b.md",
                                    "sources": [{
                                        "source": "raw/c.md",
                                        "strong": 1, "weak": 0}]}]},
          "treatment": {"events": 0, "subjects": 0,
                        "subjects_by_grade": {
                            "followed": 0, "questioned": 0,
                            "caution": 0, "negative": 0},
                        "treated_pages": [], "grounds_edges": 0,
                        "resting_pages": 0, "weakened": [],
                        "weakened_count": 0},
          "markers": {"counts": {"cite": 1, "clarify": 0,
                                 "disputed": 0},
                      "total": 1,
                      "locations": [{"page": "wiki/a.md", "line": 9,
                                     "kind": "cite",
                                     "excerpt": "A claim. {{cite}}"}]}}
    l6 = {"live": [{"file": "wiki/d.md", "line": 5,
                    "form_title": "Old form", "form_id": "f1",
                    "excerpt": "relies on it"}],
          "live_count": 1, "historical_count": 0, "forms": 1,
          "files_scanned": 3}
    la = {"count": 1, "sources": 1,
          "items": [{"source": "raw/e.md",
                     "mark": {"id": "a0001", "kind": "correction",
                              "locator": {"start": 1, "end": 2},
                              "text": "this is wrong"},
                     "pages": ["wiki/a.md"]}]}
    return {"contradictions": l1, "stale": l2, "missing": l3,
            "leaks": l4, "quotes": l5, "decision_gate": l6,
            "annotations": la}


def _lanes_empty():
    laneset = _lanes_with_findings()
    laneset["contradictions"] = {
        "count": 0, "top": None, "pages_scanned": 0,
        "statements": 0, "cases_open": 0}
    laneset["stale"] = {
        "count": 0, "oldest": [], "scanned": 0, "undated": 0,
        "cutoff": "2030-09-20", "semantic": [], "semantic_count": 0,
        "claim_pages": 0, "outcomes_recorded": 0, "talk_pages": 0,
        "attested_current": 0, "attestation_expired": [],
        "attestation_expired_count": 0, "attestation_invalid": [],
        "reverify_due": [], "reverify_due_count": 0}
    laneset["missing"] = {"broken_count": 0, "broken": [],
                          "orphan_count": 0, "orphans": [],
                          "validator_exit": 0}
    laneset["leaks"] = {"new_total": 0, "baselined_total": 0,
                        "verdict": "clean", "baseline_present": True,
                        "surfaces": []}
    laneset["quotes"] = {
        "checked": 0, "pages": 0, "verified": 0, "divergences": [],
        "caveats": {"checked": 0, "carried": 0, "findings": []},
        "treatment": laneset["quotes"]["treatment"],
        "markers": {"counts": {"cite": 0, "clarify": 0,
                               "disputed": 0},
                    "total": 0, "locations": []}}
    laneset["decision_gate"] = {"live": [], "live_count": 0,
                                "historical_count": 0, "forms": 0,
                                "files_scanned": 0}
    laneset["annotations"] = {"count": 0, "items": [], "sources": 0}
    return laneset


class TestLaneCoaching(unittest.TestCase):
    def test_every_present_class_carries_a_clear_line(self):
        report = lanes.render(_lanes_with_findings(),
                              "2030-10-20", "Lens note.")
        # One per class present: contradictions, stale-semantic,
        # attestation, reverify, broken, orphans, leaks,
        # divergences, caveats, markers, decision-gate, marks.
        self.assertGreaterEqual(report.count("**To clear this:**"),
                                10)
        self.assertIn("wiki_cases.py", report)          # Lane 1
        self.assertIn("agents never write `verified_until`",
                      report)                            # Lane 2 attestation
        self.assertIn("wiki_reverify.py", report)        # Lane 2 reverify
        self.assertIn("rotate it at its source", report)  # Lane 4
        self.assertIn("Never edit the source to match the page",
                      report)                            # Lane 5 quotes
        self.assertIn("HISTORICAL", report)              # Lane 6
        self.assertIn("^[mark: raw/<path>#aNNNN]", report)  # marks

    def test_no_findings_no_coaching(self):
        report = lanes.render(_lanes_empty(), "2030-10-20",
                              "Lens note.")
        self.assertNotIn("**To clear this:**", report)


if __name__ == "__main__":
    unittest.main()
