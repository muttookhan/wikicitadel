#!/usr/bin/env python3
"""Tests for scripts/wiki_automation_gate.py — the
automation-readiness pre-flight gate (Marathon Round 3,
Tier A: the automation-readiness gate).

Pins, on fixture manifests (dicts built in-test + the shipped
template):
  - the shipped template passes READY;
  - each criterion fails ALONE when its field is broken
    (missing owner, no schedule, idempotent:true with no
    named mechanism, no kill switch, no log path,
    owner_notice "log-only", unbounded with no stated reason,
    unstated writes) — the failure names the criterion;
  - an unbounded automation with a stated unbounded_reason
    passes as a named warning;
  - a non-object / unparseable manifest is INVALID (exit 2
    at the CLI, NOT-READY never claimed for it);
  - CLI exit codes: 0 READY, 1 NOT-READY, 2 INVALID.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "wiki_automation_gate", SCRIPTS / "wiki_automation_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = load_gate()
GOOD = copy.deepcopy(GATE.TEMPLATE)


def fails(manifest):
    verdict, checks = GATE.check_manifest(manifest)
    return verdict, {c["criterion"] for c in checks if not c["ok"]}


class TestGate(unittest.TestCase):
    def test_template_is_ready(self):
        verdict, checks = GATE.check_manifest(GOOD)
        self.assertEqual(verdict, "READY", checks)

    def test_shipped_template_file_matches_and_passes(self):
        p = REPO / "templates" / "automation-manifest.example.json"
        m = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(m, GATE.TEMPLATE)
        self.assertEqual(GATE.check_manifest(m)[0], "READY")

    def test_each_criterion_fails_alone(self):
        cases = {
            "identity": lambda m: m.update(owner=""),
            "schedule": lambda m: m.pop("schedule"),
            "idempotence": lambda m: m.update(idempotence_key=""),
            "kill_switch": lambda m: m.pop("kill_switch"),
            "log_path": lambda m: m.update(log_path=""),
            "owner_notice": lambda m: m.update(owner_notice="log-only"),
            "bounded": lambda m: m.pop("max_items_per_run"),
            "no_live_wiring": lambda m: (m.pop("writes"),
                                         m.update(dry_run_default=False)),
        }
        for criterion, break_it in cases.items():
            with self.subTest(criterion=criterion):
                m = copy.deepcopy(GOOD)
                break_it(m)
                verdict, bad = fails(m)
                self.assertEqual(verdict, "NOT-READY")
                self.assertIn(criterion, bad)

    def test_idempotent_false_fails(self):
        m = copy.deepcopy(GOOD)
        m["idempotent"] = False
        verdict, bad = fails(m)
        self.assertIn("idempotence", bad)

    def test_unbounded_with_reason_passes_named(self):
        m = copy.deepcopy(GOOD)
        m.pop("max_runtime_seconds")
        m.pop("max_items_per_run")
        m["unbounded_reason"] = "single-file pass, exits at EOF"
        verdict, checks = GATE.check_manifest(m)
        self.assertEqual(verdict, "READY", checks)
        bounded = next(c for c in checks
                       if c["criterion"] == "bounded")
        self.assertIn("unbounded", bounded["detail"])

    def test_readonly_writes_passes(self):
        m = copy.deepcopy(GOOD)
        m["writes"] = []
        self.assertEqual(GATE.check_manifest(m)[0], "READY")

    def test_non_object_invalid(self):
        verdict, _ = GATE.check_manifest([1, 2])
        self.assertEqual(verdict, "INVALID")


class TestGateCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copy(SCRIPTS / "wiki_automation_gate.py", self.root)
        self.tool = self.root / "wiki_automation_gate.py"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(self.tool), *argv],
                              capture_output=True, text=True)

    def test_cli_exit_codes(self):
        good = self.root / "good.json"
        good.write_text(json.dumps(GOOD), encoding="utf-8")
        proc = self.run_cli("check", str(good))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("READY", proc.stdout)
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"name": "x"}), encoding="utf-8")
        proc = self.run_cli("check", str(bad))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT-READY", proc.stdout)
        ugly = self.root / "ugly.json"
        ugly.write_text("{not json", encoding="utf-8")
        proc = self.run_cli("check", str(ugly))
        self.assertEqual(proc.returncode, 2)

    def test_cli_template_matches_shipped(self):
        proc = self.run_cli("template")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout), GATE.TEMPLATE)


if __name__ == "__main__":
    unittest.main()
