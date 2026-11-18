#!/usr/bin/env python3
"""Tests for scripts/wiki_hooks.py (TB3-2).

Pins the Haystack-pattern contract: hooks are data in the
register; pre hooks run before the stage and a failing pre
hook means the stage NEVER runs; the stage runs between pre
and post; a failing post hook fails the stage even when the
stage itself passed; order is register order.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "wiki_hooks", SCRIPTS / "wiki_hooks.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

TRUE = [sys.executable, "-c", "raise SystemExit(0)"]
FALSE = [sys.executable, "-c", "raise SystemExit(3)"]


def fixture(hooks):
    root = Path(tempfile.mkdtemp())
    (root / "evaluation").mkdir(parents=True)
    (root / "evaluation" / "hooks.jsonl").write_text(
        "".join(json.dumps(h) + "\n" for h in hooks), encoding="utf-8")
    return root


def cmd_hook(hid, phase, argv):
    return {"hook_id": hid, "step": "promote", "phase": phase,
            "check": {"kind": "command", "argv": argv},
            "on_fail": "halt"}


class TestHooks(unittest.TestCase):
    def test_all_pass_stage_runs(self):
        root = fixture([cmd_hook("a", "pre", TRUE),
                        cmd_hook("b", "post", TRUE)])
        ran = []
        code, report = M.run_stage(root, "promote",
                                   lambda: ran.append(1) or 0)
        self.assertEqual(code, 0)
        self.assertEqual(ran, [1])
        self.assertTrue(report["stage_ran"])

    def test_failing_pre_hook_stage_never_runs(self):
        root = fixture([cmd_hook("a", "pre", FALSE)])
        ran = []
        code, report = M.run_stage(root, "promote",
                                   lambda: ran.append(1) or 0)
        self.assertEqual(code, 1)
        self.assertEqual(ran, [])
        self.assertFalse(report["stage_ran"])

    def test_failing_post_hook_fails_stage(self):
        root = fixture([cmd_hook("a", "post", FALSE)])
        code, _report = M.run_stage(root, "promote", lambda: 0)
        self.assertEqual(code, 1)

    def test_file_exists_check(self):
        root = fixture([])
        (root / "x.txt").write_text("hi", encoding="utf-8")
        ok, _ = M.run_check(root, {"kind": "file-exists", "path": "x.txt"})
        self.assertTrue(ok)
        ok, _ = M.run_check(root, {"kind": "file-exists", "path": "y.txt"})
        self.assertFalse(ok)

    def test_other_step_hooks_ignored(self):
        root = fixture([dict(cmd_hook("a", "pre", FALSE), step="ingest")])
        code, _ = M.run_stage(root, "promote", lambda: 0)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
