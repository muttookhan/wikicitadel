"""Tests for scripts/wiki_job_reliability.py + the register
evaluation/job-runs.jsonl (Marathon R9 lane BA; tau-bench
pass^k board item).

Pins: the shipped register loads with zero runs and zero
findings (seeded empty-but-valid — populating it is
operational use); pass^k is all-must-pass over the last k
runs; a single failure inside the window fails pass^k while
an older failure outside it does not; fewer than k runs is
reported insufficient, never scored; malformed lines are
register findings, never silently dropped.

Run: python3 -m unittest scripts.tests.test_wiki_job_reliability
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_job_reliability",
        SCRIPTS / "wiki_job_reliability.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


def run(job, n, day, outcome):
    return {"kind": "run", "job": job, "run_id": f"{job}-{n}",
            "started": f"2026-10-{day:02d}", "outcome": outcome}


class ReliabilityTests(unittest.TestCase):
    def test_all_pass(self):
        runs = [run("sweep", i, i, "success") for i in (1, 2, 3)]
        rep = MOD.reliability(runs, k=3)
        self.assertTrue(rep["sweep"]["passk"])
        self.assertEqual(rep["sweep"]["window_successes"], 3)
        self.assertEqual(rep["sweep"]["success_streak"], 3)

    def test_one_failure_in_window_fails_passk(self):
        runs = [run("sweep", 1, 1, "success"),
                run("sweep", 2, 2, "failure"),
                run("sweep", 3, 3, "success"),
                run("sweep", 4, 4, "success")]
        rep = MOD.reliability(runs, k=3)
        self.assertFalse(rep["sweep"]["passk"])
        self.assertEqual(rep["sweep"]["window_successes"], 2)
        self.assertEqual(rep["sweep"]["success_streak"], 2)

    def test_old_failure_outside_window_does_not_fail(self):
        runs = [run("sweep", 1, 1, "failure")] + \
               [run("sweep", i, i, "success") for i in (2, 3, 4)]
        rep = MOD.reliability(runs, k=3)
        self.assertTrue(rep["sweep"]["passk"])
        self.assertEqual(rep["sweep"]["runs"], 4)

    def test_insufficient_runs_not_scored(self):
        runs = [run("sweep", 1, 1, "success"),
                run("sweep", 2, 2, "success")]
        rep = MOD.reliability(runs, k=3)
        self.assertIsNone(rep["sweep"]["passk"])
        self.assertIn("INSUFFICIENT",
                      MOD.render_text(rep, [], 3))

    def test_ordering_by_started_not_file_order(self):
        runs = [run("sweep", 3, 3, "failure"),
                run("sweep", 1, 1, "success"),
                run("sweep", 2, 2, "success")]
        rep = MOD.reliability(runs, k=2)
        # Last two by date are success(2nd), failure(3rd).
        self.assertFalse(rep["sweep"]["passk"])
        self.assertEqual(rep["sweep"]["latest"]["outcome"],
                         "failure")


class RegisterTests(unittest.TestCase):
    def test_shipped_register_empty_but_valid(self):
        runs, findings = MOD.load_register(
            ROOT / "evaluation" / "job-runs.jsonl")
        self.assertEqual(runs, [])
        self.assertEqual(findings, [])
        rep = MOD.reliability(runs)
        self.assertEqual(rep, {})
        self.assertIn("No runs recorded",
                      MOD.render_text(rep, findings, 3))

    def test_malformed_lines_are_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text(
                json.dumps({"kind": "header"}) + "\n"
                + json.dumps(run("sweep", 1, 1, "success"))
                + "\nnot json\n"
                + json.dumps({"kind": "run", "job": "sweep",
                              "run_id": "x", "started": "d",
                              "outcome": "maybe"}) + "\n",
                encoding="utf-8")
            runs, findings = MOD.load_register(path)
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(findings), 2)


if __name__ == "__main__":
    unittest.main()
