#!/usr/bin/env python3
"""Tests for scripts/wiki_queues.py — obligation-queue
health (item 42). The CLI is driven against a fixture repo
in a temp dir (the real scripts copied in, so every tool's
ROOT resolves to the fixture).

Fixture queues, as of 2030-10-20:
  reverify: claim-a (as_of 2030-10-13, due 2030-10-20) and
    claim-b (as_of 2030-10-19, due 2030-10-26); history
    empty.
  decisions: one draft proposal + one ideas Waiting bullet
    open; one promoted proposal NOT open.
  retention-review: one staging note filed 2030-10-01
    (mtime; no git in the fixture) under a 7-day review
    clock — expired 2030-10-08.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
NEEDS = ("wiki_queues.py", "wiki_reverify.py",
         "wiki_retention.py", "wiki_validate.py")

CLAIM_A = """---
title: Claim A
type: concept
created: 2030-10-13
updated: 2030-10-13
sources: []
tags: [fixture]
claim: "Fixture claim A."
as_of: 2030-10-13
---

Body.
"""

CLAIM_B = CLAIM_A.replace("Claim A", "Claim B").replace(
    "2030-10-13", "2030-10-19").replace("claim A", "claim B")

IDEAS = """# Ideas — awaiting your call

## Waiting for your call

- **Fixture decision** — a thing awaiting a ruling

## Approved

- **Done thing** — built
"""

POLICY = {
    "schema": "retention-policy/1", "version": 1,
    "adopted": "2030-10-20",
    "classes": [
        {"name": "staging-notes", "scope": ["staging/**"],
         "retention": {"kind": "review-after",
                       "period_days": 7},
         "on_expiry": "review"},
        {"name": "compiled-wiki", "scope": ["wiki/**"],
         "retention": {"kind": "keep-forever"},
         "on_expiry": None},
    ],
}


def build_fixture(root: Path):
    (root / "scripts").mkdir(parents=True)
    for name in NEEDS:
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "concepts" / "claim-a.md").write_text(
        CLAIM_A, encoding="utf-8")
    (root / "wiki" / "concepts" / "claim-b.md").write_text(
        CLAIM_B, encoding="utf-8")
    (root / "wiki" / "ideas.md").write_text(
        IDEAS, encoding="utf-8")
    (root / "evaluation").mkdir()
    (root / "evaluation" / "reverify-history.jsonl").write_text(
        "", encoding="utf-8")
    (root / "evaluation" / "retention-policy.json").write_text(
        json.dumps(POLICY), encoding="utf-8")
    proposed = root / "staging" / "proposed"
    proposed.mkdir(parents=True)
    (proposed / "prop-aaaa.md").write_text(
        "# Draft proposal\n", encoding="utf-8")
    (proposed / "prop-aaaa.json").write_text(json.dumps(
        {"state": "draft",
         "submitted_at": "2030-10-15T00:00:00Z"}),
        encoding="utf-8")
    (proposed / "prop-bbbb.md").write_text(
        "# Promoted proposal\n", encoding="utf-8")
    (proposed / "prop-bbbb.json").write_text(json.dumps(
        {"state": "promoted",
         "submitted_at": "2030-10-13T00:00:00Z"}),
        encoding="utf-8")
    fresh = datetime(2030, 10, 19, 12, 0).timestamp()
    for f in proposed.iterdir():
        os.utime(f, (fresh, fresh))
    note = root / "staging" / "old-note.md"
    note.write_text("# Old staging note\n", encoding="utf-8")
    stamp = datetime(2030, 10, 1, 12, 0).timestamp()
    os.utime(note, (stamp, stamp))


class QueuesFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def run_report(self, today, write=True):
        cmd = [sys.executable,
               str(self.root / "scripts" / "wiki_queues.py"),
               "report", "--root", str(self.root),
               "--today", today]
        if not write:
            cmd.append("--no-write")
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        artefact = json.loads(
            (self.root / "evaluation" / "queue-health.json")
            .read_text(encoding="utf-8")) if write else None
        return r.stdout, artefact


class MetricsTests(QueuesFixture):
    def test_first_report_numbers(self):
        _out, art = self.run_report("2030-10-20")
        rev = art["queues"]["reverify"]
        self.assertEqual(rev["open"], 2)
        self.assertEqual(rev["due"], 1)          # claim-a only
        self.assertEqual(rev["added_7d"], 1)     # claim-b
        self.assertEqual(rev["added_14d"], 2)
        self.assertEqual(rev["closed_7d"], 0)
        self.assertEqual(rev["net_7d"], 1)
        self.assertTrue(any("outpace" in w
                            for w in rev["warnings"]))
        dec = art["queues"]["decisions"]
        self.assertEqual(dec["open"], 2)   # draft + bullet
        self.assertNotIn("staging/proposed/prop-bbbb.md",
                         dec["items"])     # promoted excluded
        self.assertIsNone(dec["added_7d"])  # baseline run
        ret = art["queues"]["retention-review"]
        self.assertEqual(ret["open"], 1)
        self.assertEqual(ret["items"], ["staging/old-note.md"])
        self.assertEqual(ret["added_7d"], 0)  # expiry 10-08
        self.assertEqual(ret["added_14d"], 1)

    def test_health_ok_on_first_surfacing(self):
        _out, art = self.run_report("2030-10-20")
        for name in ("reverify", "decisions",
                     "retention-review"):
            self.assertEqual(art["queues"][name]["health"],
                             "ok")
            self.assertEqual(
                art["queues"][name]
                ["surfacing_cycles_on_batch"], 1)


class BatchFreezeTests(QueuesFixture):
    def test_batch_freezes_and_unopened_fires(self):
        self.run_report("2030-10-20")
        # 2030-10-27: claim-b is now overdue too, but the
        # batch formed on 10-20 is unacted, so it must NOT
        # absorb claim-b; and at cycle >= 2 the queue reads
        # unopened.
        _out, art = self.run_report("2030-10-27")
        rev = art["queues"]["reverify"]
        self.assertEqual(rev["batch"]["items"],
                         ["wiki/concepts/claim-a.md"])
        self.assertEqual(rev["pending_admission"],
                         ["wiki/concepts/claim-b.md"])
        self.assertEqual(rev["health"], "unopened")
        self.assertEqual(rev["due"], 2)  # the queue grew;
        # the batch did not — that is the rule, not a bug.

    def test_action_on_batch_item_reforms_batch(self):
        self.run_report("2030-10-20")
        self.run_report("2030-10-27")
        history = self.root / "evaluation" / \
            "reverify-history.jsonl"
        with history.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"claim": "wiki/concepts/claim-a.md",
                 "date": "2030-10-27", "outcome": "pass",
                 "note": "", "source": "manual"}) + "\n")
        _out, art = self.run_report("2030-10-27")
        rev = art["queues"]["reverify"]
        # claim-a was acted on: the batch re-forms from the
        # current due set (claim-b overdue; claim-a's next
        # check is in the future after a pass).
        self.assertEqual(rev["batch"]["items"],
                         ["wiki/concepts/claim-b.md"])
        self.assertEqual(rev["batch"]["formed"], "2030-10-27")
        self.assertEqual(rev["health"], "ok")
        self.assertEqual(rev["closed_7d"], 1)


if __name__ == "__main__":
    unittest.main()
