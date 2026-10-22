#!/usr/bin/env python3
"""Tests for scripts/wiki_handoff.py (wave 6, item 67).

Pins: digests are computed by the tool, not asserted by
the agent (a wrong pre-claimed digest is refused at the
door); a self-declared handoff keeps its permanent
`self-declared`/`unchecked` provenance labels whatever
later verification says; closure is DERIVED — a record is
closed only with a receiver synthesis over intact
artefacts, a tampered artefact against a 'done' claim is
`contradicted`, and an asserted status=closed with no
synthesis is flagged; the fake-closure audit names
missing artefacts, absent test files, drifted digests and
shrunk registers on fixture records, reports the absent
predicates register as a gap (not a pass), and is
byte-deterministic.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_handoff", SCRIPTS / "wiki_handoff.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def fixture():
    root = Path(tempfile.mkdtemp())
    for d in ("evaluation", "scripts",
              "wiki/syntheses", "wiki/filings"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "thing.py").write_text(
        "VALUE = 1\n", encoding="utf-8")
    return root


def record(**over):
    rec = {"kind": "handoff", "task": "build the thing",
           "scope": "fixture tree only", "from": "lane-a",
           "to": "coordinator", "sender_claim": "done",
           "sender_summary": "the thing is built",
           "artefacts": [{"path": "scripts/thing.py"}],
           "evidence": [{"rung": "repeatable-test",
                         "ref": "scripts/tests/test_x.py",
                         "note": "suite green"}],
           "gaps": [], "declared_by": "sender",
           "receiver_synthesis": None}
    rec.update(over)
    return rec


def define(root, rec):
    p = root / "rec.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return M.cmd_define(root, p)


class TestDefine(unittest.TestCase):
    def test_digest_computed_and_labels_permanent(self):
        root = fixture()
        res = define(root, record())
        self.assertTrue(res["ok"])
        self.assertEqual(res["labels"],
                         ["self-declared", "unchecked"])
        want = hashlib.sha256(
            (root / "scripts/thing.py").read_bytes()
        ).hexdigest()
        _, records = M.load_register(root)
        self.assertEqual(records[0]["artefacts"][0]
                         ["sha256"], want)
        rep = M.run_check(root)
        self.assertEqual(rep["states"][res["id"]], "open")
        self.assertEqual(rep["open"], [res["id"]])
        self.assertEqual(rep["findings"], [])

    def test_wrong_preclaimed_digest_refused(self):
        root = fixture()
        rec = record(artefacts=[{
            "path": "scripts/thing.py",
            "sha256": "0" * 64}])
        res = define(root, rec)
        self.assertFalse(res["ok"])
        self.assertIn("digest-claim-mismatch:scripts/thing.py",
                      res["problems"])

    def test_missing_artefact_refused(self):
        root = fixture()
        res = define(root, record(
            artefacts=[{"path": "scripts/nope.py"}]))
        self.assertFalse(res["ok"])

    def test_bad_rung_and_missing_gaps_refused(self):
        root = fixture()
        rec = record(evidence=[{"rung": "vibes",
                                "ref": "x"}])
        del rec["gaps"]
        res = define(root, rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any(p.startswith("bad-rung")
                            for p in res["problems"]))
        self.assertIn("missing-field:gaps", res["problems"])


class TestDerivedClosure(unittest.TestCase):
    def test_tampered_artefact_contradicts_done_claim(self):
        root = fixture()
        res = define(root, record())
        (root / "scripts/thing.py").write_text(
            "VALUE = 2\n", encoding="utf-8")
        rep = M.run_check(root)
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("hash-drifted", kinds)
        self.assertIn("claim-contradicted", kinds)
        # Provenance labels survive the contradiction.
        self.assertEqual(rep["labels"][res["id"]],
                         ["self-declared", "unchecked"])

    def test_synthesis_over_intact_artefacts_closes(self):
        root = fixture()
        res = define(root, record(receiver_synthesis={
            "by": "coordinator",
            "text": "read the artefact; it does the task",
            "verdict": "accepted"}))
        rep = M.run_check(root)
        self.assertEqual(rep["states"][res["id"]], "closed")
        self.assertEqual(rep["open"], [])

    def test_receiver_rejection_contradicts(self):
        root = fixture()
        res = define(root, record(receiver_synthesis={
            "by": "coordinator", "text": "not what was "
            "asked", "verdict": "rejected"}))
        rep = M.run_check(root)
        self.assertEqual(rep["states"][res["id"]],
                         "contradicted")

    def test_asserted_closure_flagged(self):
        root = fixture()
        res = check = M.check_record(root, record(
            status="closed"))
        kinds = {f["kind"] for f in res["findings"]}
        self.assertIn("closure-asserted-not-derived", kinds)
        self.assertEqual(res["derived_state"], "open")


class TestAudit(unittest.TestCase):
    def test_predicates_register_absent_is_a_gap(self):
        root = fixture()
        claims, findings, note = M.audit_predicates(root)
        self.assertEqual((claims, findings), (0, []))
        self.assertIn("gap", note)

    def test_close_history_shrink_and_missing_filing(self):
        root = fixture()
        (root / "evaluation/reg.jsonl").write_text(
            "{}\n{}\n{}\n", encoding="utf-8")
        close = {"kind": "close", "date": "2026-10-20",
                 "filing": "wiki/filings/close.md",
                 "register_lines": {"reg.jsonl": 5}}
        (root / "evaluation/close-history.jsonl"
         ).write_text(json.dumps(close) + "\n",
                      encoding="utf-8")
        claims, findings, _ = M.audit_close_history(root)
        kinds = {f["kind"] for f in findings}
        self.assertEqual(kinds, {"artefact-missing",
                                 "register-shrank"})
        self.assertGreaterEqual(claims, 2)

    def test_build_record_claims(self):
        root = fixture()
        (root / "scripts/tests").mkdir(parents=True)
        (root / "scripts/tests/test_real.py").write_text(
            "# t\n", encoding="utf-8")
        text = (
            "## Wave 1\n\n### W9.9 — Fixture item\n\n"
            "- **Built:** `scripts/thing.py` and "
            "`scripts/ghost.py`\n"
            "- **Tests/suites (coordinator's runs):** new "
            "`test_real` 3 OK; `test_ghost` 0 OK\n"
            "- **Commits:** private `deadbee` (pushed)\n")
        (root / M.BUILD_RECORD_REL).write_text(
            text, encoding="utf-8")
        claims, findings, _ = M.audit_build_record(root)
        kinds = {(f["kind"], f.get("path")) for f in findings}
        self.assertIn(("artefact-missing", "scripts/ghost.py"),
                      kinds)
        self.assertIn(("test-artefact-absent", "test_ghost"),
                      kinds)
        # Fixture is not a git repo: the commit claim is
        # counted, never found against.
        self.assertFalse(any(f["kind"] ==
                             "commit-unresolvable"
                             for f in findings))

    def test_checkpoint_message_file_missing(self):
        root = fixture()
        cp = {"kind": "checkpoint", "id": "cp-000099",
              "signature": {"message_file":
                            "evaluation/checkpoints.d/"
                            "cp-000099.json"},
              "provenance": {
                  "manifest": "evaluation/merkle.jsonl",
                  "manifest_sha256":
                      hashlib.sha256(b"x").hexdigest()},
              "black_box": {"file": "wiki/access/bb.jsonl"}}
        (root / "evaluation/checkpoints.jsonl").write_text(
            json.dumps(cp) + "\n", encoding="utf-8")
        (root / "evaluation/merkle.jsonl").write_text(
            "x", encoding="utf-8")
        (root / "wiki/access").mkdir(parents=True)
        (root / "wiki/access/bb.jsonl").write_text(
            "{}\n", encoding="utf-8")
        claims, findings, _ = M.audit_checkpoints(root)
        kinds = {f["kind"] for f in findings}
        self.assertIn("artefact-missing", kinds)
        self.assertNotIn("hash-drifted", kinds)

    def test_audit_deterministic(self):
        root = fixture()
        define(root, record())
        a = json.dumps(M.run_audit(root), sort_keys=True)
        b = json.dumps(M.run_audit(root), sort_keys=True)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
