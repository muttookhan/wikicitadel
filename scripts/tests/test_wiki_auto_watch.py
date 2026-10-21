#!/usr/bin/env python3
"""Tests for scripts/wiki_auto_watch.py — the gap-9 standing
auto-watch (Marathon Round 3, Tier A half of gap 9).

Fixture-based: a temp tree holding copies of the watcher,
the automation gate and the REAL ingest queue, a drop dir,
and a watch manifest whose automation block passes the gate.

Pins:
  - a first pass offers every arrival to the queue (the
    queue's register gains exactly those items);
  - a second pass (and a RESTART — a fresh process) offers
    nothing twice: the queue register does not grow and the
    pass reports all-unchanged;
  - a content-changed file is offered again as a new queue
    item; a vanished file drops out of the state, so an
    identical re-drop is offered fresh;
  - a torn state file is refused, never silently reset;
  - the gate is enforced: a manifest whose automation block
    fails the gate makes `run` refuse (exit 1) before any
    pass, and `check-gate` names the failure;
  - the stop-file kill switch ends a run cleanly;
  - --dry-run offers nothing and writes no state.

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
REPO = SCRIPTS.parent
NEEDS = ("wiki_auto_watch.py", "wiki_automation_gate.py",
         "wiki_ingest_queue.py")


def manifest(drop="raw/inbox", notice="log+chat"):
    return {
        "name": "fixture-watch",
        "state_path": "evaluation/auto-watch-state.json",
        "log_path": "evaluation/auto-watch.log",
        "watches": [{"path": drop, "kind": "ingest"}],
        "automation": {
            "name": "fixture-watch",
            "owner": "owner",
            "command": ["python3", "scripts/wiki_auto_watch.py",
                        "run", "--manifest", "watch.json"],
            "schedule": {"kind": "interval", "seconds": 60},
            "idempotent": True,
            "idempotence_key": "content-hash state + queue "
                               "content-hash identity",
            "kill_switch": {"kind": "stop-file",
                            "value": "evaluation/auto-watch.STOP"},
            "log_path": "evaluation/auto-watch.log",
            "owner_notice": notice,
            "max_runtime_seconds": 60,
            "max_items_per_run": 100,
            "writes": ["evaluation/auto-watch-state.json",
                       "evaluation/ingest-queue.jsonl"],
            "dry_run_default": False,
        },
    }


class AutoWatchFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        for name in NEEDS:
            shutil.copy(SCRIPTS / name, self.root / "scripts" / name)
        self.tool = self.root / "scripts" / "wiki_auto_watch.py"
        self.drop = self.root / "raw" / "inbox"
        self.drop.mkdir(parents=True)
        self.manifest = self.root / "watch.json"
        self.manifest.write_text(json.dumps(manifest()),
                                 encoding="utf-8")
        self.register = self.root / "evaluation" / "ingest-queue.jsonl"
        self.state = self.root / "evaluation" / "auto-watch-state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tool), *argv],
            capture_output=True, text=True)

    def run_once(self, *extra):
        proc = self.run_cli("run", "--manifest", str(self.manifest),
                            "--once", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def queue_items(self):
        proc = subprocess.run(
            [sys.executable,
             str(self.root / "scripts" / "wiki_ingest_queue.py"),
             "--root", str(self.root), "list", "--json"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["items"]


class TestAutoWatch(AutoWatchFixture):
    def test_first_pass_offers_and_restart_reoffers_nothing(self):
        (self.drop / "a.md").write_text("alpha arrival\n",
                                        encoding="utf-8")
        (self.drop / "b.md").write_text("beta arrival\n",
                                        encoding="utf-8")
        proc = self.run_once()
        self.assertIn("2 offered", proc.stdout)
        self.assertEqual(len(self.queue_items()), 2)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(state["offered"]), 2)
        # Restart: a fresh process, same state.
        proc = self.run_once()
        self.assertIn("0 offered", proc.stdout)
        self.assertIn("2 unchanged", proc.stdout)
        self.assertEqual(len(self.queue_items()), 2)

    def test_changed_file_reoffered_vanished_dropped(self):
        a = self.drop / "a.md"
        a.write_text("version one\n", encoding="utf-8")
        self.run_once()
        a.write_text("version two changed\n", encoding="utf-8")
        proc = self.run_once()
        self.assertIn("1 offered", proc.stdout)
        self.assertEqual(len(self.queue_items()), 2)
        a.unlink()
        proc = self.run_once()
        self.assertIn("1 vanished", proc.stdout)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["offered"], {})
        a.write_text("version two changed\n", encoding="utf-8")
        proc = self.run_once()  # identical re-drop offered fresh
        self.assertIn("1 offered", proc.stdout)
        self.assertEqual(len(self.queue_items()), 2)  # queue dedupes

    def test_subdir_recursion(self):
        sub = self.drop / "deep"
        sub.mkdir()
        (sub / "c.md").write_text("deep arrival\n", encoding="utf-8")
        self.run_once()
        self.assertEqual(len(self.queue_items()), 1)

    def test_glob_watch_entry(self):
        m = manifest(drop="raw/inbox/*.md")
        self.manifest.write_text(json.dumps(m), encoding="utf-8")
        (self.drop / "top.md").write_text("top\n", encoding="utf-8")
        sub = self.drop / "deep"
        sub.mkdir()
        (sub / "c.md").write_text("deep\n", encoding="utf-8")
        self.run_once()
        items = self.queue_items()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["path"].endswith("top.md"))

    def test_torn_state_refused(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text("{torn", encoding="utf-8")
        (self.drop / "a.md").write_text("x\n", encoding="utf-8")
        proc = self.run_cli("run", "--manifest", str(self.manifest),
                            "--once")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not parse", proc.stderr)

    def test_gate_blocks_unready_manifest(self):
        self.manifest.write_text(
            json.dumps(manifest(notice="log-only")),
            encoding="utf-8")
        proc = self.run_cli("check-gate", "--manifest",
                            str(self.manifest))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT-READY", proc.stdout)
        self.assertIn("owner_notice", proc.stdout)
        proc = self.run_cli("run", "--manifest", str(self.manifest),
                            "--once")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("refusing to run unattended", proc.stderr)
        self.assertFalse(self.register.exists())

    def test_template_passes_gate(self):
        tmpl = REPO / "templates" / "watch-manifest.example.json"
        m = json.loads(tmpl.read_text(encoding="utf-8"))
        dest = self.root / "tmpl.json"
        dest.write_text(json.dumps(m), encoding="utf-8")
        proc = self.run_cli("check-gate", "--manifest", str(dest))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("READY", proc.stdout)

    def test_stop_file_ends_run(self):
        (self.root / "evaluation").mkdir(parents=True, exist_ok=True)
        (self.root / "evaluation" / "auto-watch.STOP").write_text(
            "stop\n", encoding="utf-8")
        (self.drop / "a.md").write_text("x\n", encoding="utf-8")
        proc = self.run_once()
        self.assertIn("stopping cleanly", proc.stdout)
        self.assertFalse(self.register.exists())

    def test_dry_run_writes_nothing(self):
        (self.drop / "a.md").write_text("x\n", encoding="utf-8")
        proc = self.run_once("--dry-run")
        self.assertIn("1 offered", proc.stdout)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.register.exists())


if __name__ == "__main__":
    unittest.main()
