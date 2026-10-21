#!/usr/bin/env python3
"""Tests for scripts/wiki_ingest_queue.py — the persistent,
crash-recovering ingest queue (15-gap item 9).

The CLI is driven against a fixture repo in a temp dir (the
real script copied in, so the tool's DEFAULT_ROOT resolves
to the fixture), mirroring test_wiki_ocr_queue.py. No test
touches the real register.

Run:  python3 -m unittest discover -s scripts/tests -v
      (or just this file: python3 -m unittest
       scripts.tests.test_wiki_ingest_queue -v — from the
       repo root the discover form is the reliable one)
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
NEEDS = ("wiki_ingest_queue.py",)


class IngestQueueFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        for name in NEEDS:
            shutil.copy(SCRIPTS / name, self.root / "scripts")
        (self.root / "incoming").mkdir(parents=True)
        self.tool = self.root / "scripts" / "wiki_ingest_queue.py"
        self.register = (self.root / "evaluation"
                         / "ingest-queue.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tool), *argv],
            capture_output=True, text=True)

    def write_source(self, name, text):
        p = self.root / "incoming" / name
        p.write_text(text, encoding="utf-8")
        return p

    def enqueue(self, path, *extra):
        proc = self.run_cli("enqueue", str(path), *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def items(self, *extra):
        proc = self.run_cli("list", "--json", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["items"]

    def claim(self, *extra):
        proc = self.run_cli("claim", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = re.match(r"claimed (\S+):", proc.stdout)
        self.assertIsNotNone(m, proc.stdout)
        return m.group(1), proc


class HappyPathTests(IngestQueueFixture):
    def test_enqueue_list_claim_complete(self):
        a = self.write_source("a.md", "# A\n")
        b = self.write_source("b.md", "# B\n")
        proc = self.enqueue(a)
        self.assertIn("enqueued", proc.stdout)
        self.enqueue(b)
        items = self.items()
        self.assertEqual(len(items), 2)
        self.assertEqual([i["state"] for i in items],
                         ["pending", "pending"])
        self.assertEqual(items[0]["path"], "incoming/a.md")
        self.assertEqual(items[0]["job_kind"], "ingest")
        self.assertTrue(items[0]["content_hash"])

        # claim leases the OLDEST pending item first
        claimed_id, proc = self.claim("--worker", "w1")
        self.assertEqual(claimed_id, items[0]["id"])
        self.assertIn("worker=w1", proc.stdout)
        self.assertIn("lease_expires=", proc.stdout)
        items = self.items()
        self.assertEqual(items[0]["state"], "claimed")
        self.assertEqual(items[0]["worker"], "w1")
        self.assertIsNotNone(items[0]["lease_expires"])
        self.assertEqual(items[1]["state"], "pending")

        proc = self.run_cli("complete", claimed_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = self.items()
        self.assertEqual(items[0]["state"], "done")
        self.assertIsNotNone(items[0]["completed_at"])
        # state filter sees exactly the done item
        done = self.items("--state", "done")
        self.assertEqual([i["id"] for i in done], [claimed_id])
        pending = self.items("--state", "pending")
        self.assertEqual([i["id"] for i in pending],
                         [items[1]["id"]])

    def test_fail_records_reason(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        claimed_id, _ = self.claim("--worker", "w1")
        proc = self.run_cli("fail", claimed_id, "--reason",
                            "converter choked on a table")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        item = self.items()[0]
        self.assertEqual(item["state"], "failed")
        self.assertEqual(item["fail_reason"],
                         "converter choked on a table")

    def test_kind_is_part_of_identity(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        proc = self.enqueue(a, "--kind", "compile")
        self.assertIn("enqueued", proc.stdout)
        self.assertEqual(len(self.items()), 2)


class IdempotenceTests(IngestQueueFixture):
    def test_reenqueue_same_file_is_already_queued(self):
        a = self.write_source("a.md", "# A\n")
        first = self.enqueue(a)
        first_id = self.items()[0]["id"]
        second = self.enqueue(a)
        self.assertIn("already-queued", second.stdout)
        self.assertIn(first_id, second.stdout)
        self.assertNotEqual(first.stdout, second.stdout)
        self.assertEqual(len(self.items()), 1)
        # and no duplicate event was appended for it
        events = [json.loads(l) for l in
                  self.register.read_text().splitlines() if l]
        enqueued = [e for e in events
                    if e.get("kind") == "enqueued"]
        self.assertEqual(len(enqueued), 1)

    def test_changed_file_is_a_new_item(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        a.write_text("# A, revised\n", encoding="utf-8")
        proc = self.enqueue(a)
        self.assertIn("enqueued", proc.stdout)
        self.assertEqual(len(self.items()), 2)


class RefusalTests(IngestQueueFixture):
    def test_claim_on_empty_queue(self):
        proc = self.run_cli("claim")
        self.assertEqual(proc.returncode, 3)  # documented code
        self.assertEqual(proc.stdout, "")

    def test_complete_before_claim_refused(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        item_id = self.items()[0]["id"]
        proc = self.run_cli("complete", item_id)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unclaimed", proc.stderr)
        self.assertEqual(self.items()[0]["state"], "pending")

    def test_complete_unknown_id_refused(self):
        proc = self.run_cli("complete", "ingest-deadbeef")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no queue item", proc.stderr)

    def test_complete_by_wrong_worker_refused(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        claimed_id, _ = self.claim("--worker", "w1")
        proc = self.run_cli("complete", claimed_id,
                            "--worker", "w2")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("claimed by 'w1'", proc.stderr)
        self.assertEqual(self.items()[0]["state"], "claimed")


class CrashRecoveryTests(IngestQueueFixture):
    def test_expired_lease_recovers_and_reclaims(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        # worker w1 claims with a zero-length lease and dies:
        # no complete, no fail — the lease is already expired
        claimed_id, _ = self.claim("--worker", "w1",
                                   "--lease-seconds", "0")
        # a late complete from the dead lease is refused
        proc = self.run_cli("complete", claimed_id)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("lease expired", proc.stderr)

        proc = self.run_cli("recover")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("recovered", proc.stdout)
        item = self.items()[0]
        self.assertEqual(item["state"], "pending")
        self.assertEqual(item["recoveries"], 1)
        self.assertIsNone(item["worker"])

        # another worker reclaims the same item and finishes
        reclaimed_id, _ = self.claim("--worker", "w2")
        self.assertEqual(reclaimed_id, claimed_id)
        proc = self.run_cli("complete", reclaimed_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.items()[0]["state"], "done")

    def test_recover_leaves_live_leases_alone(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        self.claim("--worker", "w1")  # default lease: live
        proc = self.run_cli("recover")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("0 item(s)", proc.stdout)
        self.assertEqual(self.items()[0]["state"], "claimed")


class TornLineTests(IngestQueueFixture):
    def test_torn_last_line_tolerated(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        # simulate a crash mid-append: partial JSON, no \n
        with self.register.open("a", encoding="utf-8") as fh:
            fh.write('{"kind": "claimed", "id": "ingest-')
        proc = self.run_cli("list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("torn", proc.stderr)
        self.assertIn("incoming/a.md", proc.stdout)
        self.assertEqual(self.items()[0]["state"], "pending")
        # the queue still works afterwards: the next append
        # terminates the torn line instead of merging with it
        claimed_id, _ = self.claim("--worker", "w1")
        self.assertEqual(self.items()[0]["state"], "claimed")
        proc = self.run_cli("complete", claimed_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.items()[0]["state"], "done")


class WatchTests(IngestQueueFixture):
    def setUp(self):
        super().setUp()
        self.watch_dir = self.root / "watched"
        self.watch_dir.mkdir()

    def watch_once(self):
        proc = self.run_cli("watch", "--dir",
                            str(self.watch_dir), "--once")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def test_watch_once_enqueues_new_not_unchanged(self):
        (self.watch_dir / "one.md").write_text(
            "# One\n", encoding="utf-8")
        proc = self.watch_once()
        self.assertIn("1 new item(s)", proc.stdout)
        items = self.items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["path"], "watched/one.md")

        # second pass over the unchanged directory: nothing new
        proc = self.watch_once()
        self.assertIn("0 new item(s)", proc.stdout)
        self.assertEqual(len(self.items()), 1)

        # a genuinely new file IS picked up on the next pass
        (self.watch_dir / "two.md").write_text(
            "# Two\n", encoding="utf-8")
        proc = self.watch_once()
        self.assertIn("1 new item(s)", proc.stdout)
        self.assertEqual(len(self.items()), 2)

    def test_watch_changed_file_enqueues_new_item(self):
        target = self.watch_dir / "one.md"
        target.write_text("# One\n", encoding="utf-8")
        self.watch_once()
        target.write_text("# One, changed\n",
                          encoding="utf-8")
        proc = self.watch_once()
        self.assertIn("1 new item(s)", proc.stdout)
        self.assertEqual(len(self.items()), 2)


class PiopChecklistTests(IngestQueueFixture):
    """PIOP stage checklist (Marathon R13, Round 11 RA find 9;
    Oh 2019 — Simmons): the six stages are the register
    header's checklist and every item shows its stage."""

    STAGES = ["initiation", "identification",
              "temporary-categorisation", "examination-comparison",
              "selection-modification-creation", "categorisation"]

    def _json_doc(self):
        proc = self.run_cli("list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_header_carries_the_six_stage_checklist(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        events = [json.loads(l) for l in
                  self.register.read_text(encoding="utf-8").splitlines()
                  if l.strip()]
        header = events[0]
        self.assertEqual(header["kind"], "header")
        self.assertEqual([c["stage"] for c in header["piop_checklist"]],
                         self.STAGES)
        doc = self._json_doc()
        self.assertEqual([c["stage"] for c in doc["piop_checklist"]],
                         self.STAGES)

    def test_new_item_stands_at_initiation(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        item = self.items()[0]
        self.assertEqual(item["piop_stage"], "initiation")
        reached = [c["stage"] for c in item["piop_checklist"] if c["reached"]]
        self.assertEqual(reached, ["initiation"])

    def test_stage_event_moves_item_and_checklist(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        item_id = self.items()[0]["id"]
        proc = self.run_cli("stage", item_id, "--stage",
                            "temporary-categorisation")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("temporary-categorisation", proc.stdout)
        item = self.items()[0]
        self.assertEqual(item["piop_stage"], "temporary-categorisation")
        reached = [c["stage"] for c in item["piop_checklist"] if c["reached"]]
        self.assertEqual(reached, self.STAGES[:3])
        # plain list shows the checklist header and the item's stage
        proc = self.run_cli("list")
        self.assertIn("PIOP checklist:", proc.stdout)
        self.assertIn("piop=temporary-categorisation", proc.stdout)

    def test_stage_refused_for_unknown_and_terminal_items(self):
        a = self.write_source("a.md", "# A\n")
        self.enqueue(a)
        proc = self.run_cli("stage", "no-such-id", "--stage", "identification")
        self.assertEqual(proc.returncode, 2)
        claimed_id, _ = self.claim("--worker", "w1")
        proc = self.run_cli("complete", claimed_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_cli("stage", claimed_id, "--stage", "categorisation")
        self.assertEqual(proc.returncode, 2)
        # a bogus stage name is a usage error, never recorded
        proc = self.run_cli("stage", claimed_id, "--stage", "Bogus")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
