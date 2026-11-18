#!/usr/bin/env python3
"""Tests for scripts/wiki_decision_records.py (build-list
wave 5: decision-record upgrades — the v2 register).

Pins the contract on a FIXTURE repo in a temp dir:

  - build merges v1 (verbatim) + overlay (the fields only
    the human record carries) + the decision-basis
    artefact into evaluation/decision-records.json with
    the full v2 field set, byte-identical across runs;
  - a decision in v1 but absent from the overlay is built
    with chosen = null and flagged FIELD GAP, never
    silently half-migrated;
  - null is a VALUE for redecided / supersedes /
    superseded_by (presence required, null allowed);
  - check flags REGISTER DRIFT (a verbatim field tampered),
    CHAIN BROKEN (asymmetric supersedes pair; form chain
    diverging from v1), BASIS CHANGED / BASIS MISSING
    (hashes recomputed against the basis artefact);
  - OUTCOME GAP surfaces without failing the check;
  - reopen_when conditions re-evaluate: a date condition
    fires at --today, an owner-ruling condition reports
    MANUAL, a basis-changed condition fires when a basis
    file moved;
  - the reproposal measurement counts ideas-board waiting
    bullets mentioning a rejected option's phrases;
  - overlap ranks a re-proposal of a rejected option
    first, labels it REJECTED OPTION, and is
    deterministic; template prints every required field.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SENTINEL = "not-recorded-at-the-time"


def run(root, *args):
    return subprocess.run(
        [sys.executable,
         str(root / "scripts" / "wiki_decision_records.py"),
         "--root", str(root), *args],
        capture_output=True, text=True)


def sha256_file(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


class RecordsFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wiki-drec-"))
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / "wiki_decision_records.py",
                     self.repo / "scripts" /
                     "wiki_decision_records.py")
        (self.repo / "wiki" / "syntheses").mkdir(parents=True)
        (self.repo / "evaluation").mkdir(parents=True)
        self.decisions_page = (self.repo / "wiki" / "syntheses"
                               / "decisions.md")
        self.decisions_page.write_text("# Decisions\n\n"
                                       "The record.\n")
        self.design_page = (self.repo / "wiki" / "syntheses"
                            / "design.md")
        self.design_page.write_text("# Design\n\nBasis v1.\n")
        self.write_v1()
        self.write_basis()
        self.write_overlay()
        (self.repo / "wiki" / "ideas.md").write_text(
            "# Ideas\n\n## Waiting for your call\n\n"
            "- **Bring back the rights gate for new sources** "
            "— a proposal\n"
            "- **Something unrelated entirely** — zzz\n\n"
            "## Approved\n\n- a done thing\n")
        (self.repo / "evaluation" /
         "decision-watches.jsonl").write_text(
            json.dumps({"kind": "watch",
                        "decision": "fx-d1"}) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fixture writers ------------------------------------
    def write_v1(self, extra=()):
        lines = [{"kind": "header",
                  "register": "decisions-register"},
                 {"kind": "decision", "id": "fx-d1",
                  "title": "Fixture gate decision",
                  "status": "active", "decided": "2026-01-10",
                  "redecided": "2026-02-01",
                  "decided_by": "owner",
                  "source": {"page": "wiki/syntheses/decisions.md",
                             "section": "1"},
                  "current_form": "The gate is OPEN.",
                  "superseded_forms": [
                      {"form_id": "fx-d1-closed",
                       "title": "Gate stays closed",
                       "status": "superseded",
                       "superseded_on": "2026-02-01",
                       "superseded_by": "Owner ruling "
                                        "2026-02-01"}]},
                 {"kind": "decision", "id": "fx-d2",
                  "title": "Fixture plain decision",
                  "status": "active", "decided": "2026-01-12",
                  "decided_by": "owner",
                  "source": {"page": "wiki/syntheses/decisions.md",
                             "section": "2"},
                  "current_form": "The plain thing stands.",
                  "superseded_forms": []}]
        lines.extend(extra)
        (self.repo / "evaluation" /
         "decisions-register.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n")

    def write_basis(self):
        doc = {"kind": "decision-basis", "version": 1,
               "generated": "2026-01-15",
               "decisions": [
                   {"id": "fx-d1", "basis_status": "derived",
                    "basis": [{"path": "wiki/syntheses/decisions.md",
                               "sha256_now": sha256_file(
                                   self.decisions_page)}]},
                   {"id": "fx-d2", "basis_status": "derived",
                    "basis": [{"path": "wiki/syntheses/design.md",
                               "sha256_now": sha256_file(
                                   self.design_page)}]}]}
        (self.repo / "evaluation" /
         "decision-basis.json").write_text(json.dumps(doc))

    def write_overlay(self, d2_outcome=None, d2_reopen=None,
                      d2_superseded_by=None):
        overlay = {"kind": "decision-records-overlay",
                   "version": 1, "decisions": {
                       "fx-d1": {
                           "chosen": "The gate is OPEN",
                           "rejected": [{
                               "option": "Keep the rights gate "
                                         "in force",
                               "why_lost": SENTINEL,
                               "recorded_rationale": None,
                               "disposition":
                                   "superseded-form",
                               "superseded_on": "2026-02-01",
                               "match_phrases": ["rights gate"]}],
                           "reversibility": {
                               "class": "reversible",
                               "grounding": "demonstrated: "
                                            "redecided "
                                            "2026-02-01"},
                           "commits": [{"hash": "abc1234",
                                        "relation": "fixture"}],
                           "outcome": {
                               "status": "recorded",
                               "text": "Opened; in use.",
                               "source": "fixture record"}},
                       "fx-d2": {
                           "chosen": "The plain thing stands",
                           "rejected": [{
                               "option": "Drop the plain thing",
                               "why_lost": SENTINEL,
                               "recorded_rationale": None,
                               "disposition":
                                   "rejected-at-decision",
                               "match_phrases": []}],
                           "reversibility": {
                               "class": SENTINEL,
                               "grounding": None},
                           "commits": [],
                           "outcome": d2_outcome or {
                               "status": "not-recorded",
                               "text": None, "source": None}}}}
        if d2_reopen is not None:
            overlay["decisions"]["fx-d2"]["reopen_when"] = \
                d2_reopen
        if d2_superseded_by is not None:
            overlay["decisions"]["fx-d2"]["superseded_by"] = \
                d2_superseded_by
        (self.repo / "evaluation" /
         "decision-records-overlay.json").write_text(
            json.dumps(overlay))

    def build(self):
        r = run(self.repo, "build")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads((self.repo / "evaluation" /
                           "decision-records.json").read_text())

    # -- tests -----------------------------------------------
    def test_build_full_field_set(self):
        reg = self.build()
        d1 = reg["decisions"][0]
        for f in ("id", "title", "status", "decided",
                  "redecided", "decided_by", "tier", "source",
                  "current_form", "chosen", "rejected",
                  "reversibility", "reopen_when", "basis",
                  "commits", "outcome", "supersedes",
                  "superseded_by", "form_supersessions",
                  "watch_records"):
            self.assertIn(f, d1)
        self.assertEqual(d1["current_form"], "The gate is OPEN.")
        self.assertEqual(d1["rejected"][0]["why_lost"], SENTINEL)
        self.assertEqual(d1["form_supersessions"],
                         [{"form_id": "fx-d1-closed",
                           "superseded_on": "2026-02-01"}])
        self.assertEqual(d1["watch_records"], 1)
        self.assertEqual(d1["basis"]["files"],
                         ["wiki/syntheses/decisions.md"])
        self.assertEqual(reg["open_references"]
                         ["count_at_build"], 2)

    def test_build_byte_identical(self):
        self.build()
        first = (self.repo / "evaluation" /
                 "decision-records.json").read_bytes()
        self.build()
        second = (self.repo / "evaluation" /
                  "decision-records.json").read_bytes()
        self.assertEqual(first, second)

    def test_null_is_a_value_not_a_gap(self):
        self.build()
        r = run(self.repo, "check", "--today", "2026-03-01")
        self.assertNotIn("FIELD GAP fx-d1: supersedes",
                         r.stdout)
        self.assertNotIn("FIELD GAP fx-d2: redecided",
                         r.stdout)

    def test_check_clean_of_hard_findings(self):
        self.build()
        r = run(self.repo, "check", "--today", "2026-03-01")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("OUTCOME GAP fx-d2", r.stdout)
        self.assertIn("REOPEN MANUAL fx-d1", r.stdout)

    def test_unmigrated_decision_flags_field_gap(self):
        self.write_v1(extra=[{
            "kind": "decision", "id": "fx-d3",
            "title": "Unmigrated", "status": "active",
            "decided": "2026-01-20", "decided_by": "owner",
            "source": {"page": "wiki/syntheses/decisions.md",
                       "section": "3"},
            "current_form": "A third thing.",
            "superseded_forms": []}])
        self.build()
        r = run(self.repo, "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FIELD GAP fx-d3: chosen", r.stdout)
        r2 = run(self.repo, "check", "--report")
        self.assertEqual(r2.returncode, 0)

    def test_basis_changed_and_missing(self):
        self.build()
        self.decisions_page.write_text("# Decisions\n\n"
                                       "Changed bytes.\n")
        r = run(self.repo, "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BASIS CHANGED fx-d1: "
                      "wiki/syntheses/decisions.md", r.stdout)
        self.decisions_page.unlink()
        r = run(self.repo, "check")
        self.assertIn("BASIS MISSING fx-d1: "
                      "wiki/syntheses/decisions.md", r.stdout)

    def test_register_drift_detected(self):
        reg = self.build()
        reg["decisions"][0]["current_form"] = "Tampered."
        (self.repo / "evaluation" /
         "decision-records.json").write_text(json.dumps(reg))
        r = run(self.repo, "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("REGISTER DRIFT fx-d1: current_form",
                      r.stdout)

    def test_chain_broken_when_asymmetric(self):
        self.write_overlay(d2_superseded_by={
            "decision": "fx-d1", "on": "2026-03-01"})
        self.build()
        r = run(self.repo, "check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("CHAIN BROKEN fx-d2: superseded_by fx-d1",
                      r.stdout)

    def test_form_chain_tamper_detected(self):
        reg = self.build()
        reg["decisions"][0]["form_supersessions"] = []
        (self.repo / "evaluation" /
         "decision-records.json").write_text(json.dumps(reg))
        r = run(self.repo, "check")
        self.assertIn("CHAIN BROKEN fx-d1: form_supersessions",
                      r.stdout)

    def test_reopen_date_condition(self):
        self.write_overlay(d2_reopen=[
            {"type": "owner-ruling", "text": "owner reopens"},
            {"type": "date", "date": "2026-06-01",
             "text": "review by June"}])
        self.build()
        before = run(self.repo, "check", "--today",
                     "2026-05-31")
        self.assertNotIn("REOPEN TRIGGERED fx-d2",
                         before.stdout)
        after = run(self.repo, "check", "--today",
                    "2026-06-01")
        self.assertIn("REOPEN TRIGGERED fx-d2: reopen date "
                      "2026-06-01", after.stdout)

    def test_reopen_basis_changed_condition(self):
        self.write_overlay(d2_reopen=[
            {"type": "basis-changed",
             "text": "reopens if its basis moves"}])
        self.build()
        self.design_page.write_text("# Design\n\nMoved.\n")
        r = run(self.repo, "check")
        self.assertIn("REOPEN TRIGGERED fx-d2: a basis file "
                      "changed", r.stdout)

    def test_reproposal_measurement(self):
        self.build()
        r = run(self.repo, "check")
        self.assertIn("REPROPOSAL CANDIDATE fx-d1", r.stdout)
        self.assertIn("REPROPOSALS MEASURED: 1 of 2 rejected "
                      "options", r.stdout)

    def test_overlap_ranks_rejected_option_first(self):
        self.build()
        r = run(self.repo, "overlap", "--text",
                "Keep the rights gate in force for sources")
        self.assertEqual(r.returncode, 0)
        first = r.stdout.splitlines()[0]
        self.assertIn("REJECTED OPTION", first)
        self.assertIn("fx-d1", first)
        r2 = run(self.repo, "overlap", "--text",
                 "Keep the rights gate in force for sources")
        self.assertEqual(r.stdout, r2.stdout)

    def test_template_has_all_fields(self):
        r = run(self.repo, "template")
        self.assertEqual(r.returncode, 0)
        blank = json.loads(r.stdout)
        for f in ("id", "title", "status", "decided",
                  "redecided", "decided_by", "tier", "source",
                  "current_form", "chosen", "rejected",
                  "reversibility", "reopen_when", "basis",
                  "commits", "outcome", "supersedes",
                  "superseded_by", "form_supersessions",
                  "watch_records"):
            self.assertIn(f, blank)


if __name__ == "__main__":
    unittest.main()
