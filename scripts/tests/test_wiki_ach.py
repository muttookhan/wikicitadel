#!/usr/bin/env python3
"""Tests for scripts/wiki_ach.py — ACH as bookkeeping
(item 37): matrix creation, caller scoring, inconsistency
counts (raw and witness-adjusted), the diagnosticity view,
and register integrity.

The tool never scores a cell itself; these tests score cells
by hand through the module API and the CLI and check the
bookkeeping arithmetic — including the shared-witness rule
(correlated evidence counts once) and the non-diagnostic
flag (evidence consistent with every hypothesis separates
nothing).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_ach():
    spec = importlib.util.spec_from_file_location(
        "wiki_ach", SCRIPTS / "wiki_ach.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ach = load_ach()
CITE = "AGENTS.md"          # a path that resolves in the real repo


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reg = self.tmp / "ach-matrices.jsonl"
        m = ach.new_matrix("ach-t1", "Is the claim accurate?",
                           ["accurate", "partly", "inaccurate"],
                           by="test")
        m = ach.append_revision(m, self.reg)
        self.m = m

    def build(self):
        m = self.m
        ach.add_evidence(m, "consistent with everything",
                         CITE)                                    # E1
        ach.add_evidence(m, "cuts against H1 only", CITE)         # E2
        ach.add_evidence(m, "correlated twin A", CITE,
                         witness="pair")                          # E3
        ach.add_evidence(m, "correlated twin B", CITE,
                         witness="pair")                          # E4
        ach.add_evidence(m, "never scored", CITE)                 # E5
        for h in ("H1", "H2", "H3"):
            ach.score_cell(m, "E1", h, "C", CITE, by="test")
        ach.score_cell(m, "E2", "H1", "I", CITE, by="test")
        ach.score_cell(m, "E2", "H2", "C", CITE, by="test")
        ach.score_cell(m, "E2", "H3", "C", CITE, by="test")
        for eid in ("E3", "E4"):
            ach.score_cell(m, eid, "H1", "I", CITE, by="test")
            ach.score_cell(m, eid, "H2", "C", CITE, by="test")
            ach.score_cell(m, eid, "H3", "NA", CITE, by="test")
        return ach.append_revision(m, self.reg)

    def test_crud_and_fold(self):
        self.assertEqual(self.m["revision"], 1)
        self.assertEqual([h["id"] for h in self.m["hypotheses"]],
                         ["H1", "H2", "H3"])
        m2 = self.build()
        folded = ach.fold(ach.load_lines(self.reg))
        self.assertEqual(folded["ach-t1"]["revision"], 2)
        self.assertEqual(len(folded["ach-t1"]["evidence"]), 5)
        self.assertEqual(len(folded["ach-t1"]["cells"]), 12)
        self.assertEqual(m2["id"], "ach-t1")

    def test_counts_raw_and_witness_adjusted(self):
        m = self.build()
        raw, adjusted = ach.inconsistency_counts(m)
        # H1: E2 + E3 + E4 = 3 raw; the E3/E4 pair is one witness.
        self.assertEqual(raw, {"H1": 3, "H2": 0, "H3": 0})
        self.assertEqual(adjusted, {"H1": 2, "H2": 0, "H3": 0})

    def test_diagnosticity(self):
        m = self.build()
        diag = ach.diagnosticity(m)
        self.assertEqual(diag["E1"], "non-diagnostic")
        self.assertEqual(diag["E2"], "discriminating")
        self.assertEqual(diag["E3"], "discriminating")
        self.assertEqual(diag["E5"], "unscored")

    def test_render_carries_the_caveat_and_survivor(self):
        text = ach.render(self.build())
        self.assertIn("Karvetski & Mandel", text)
        self.assertIn("LEAST evidence against it", text)
        self.assertIn("NON-DIAGNOSTIC", text)
        self.assertIn("Least-inconsistent (witness-adjusted): H2",
                      text)

    def test_score_rejects_bad_value_and_unknown_ids(self):
        m = self.m
        ach.add_evidence(m, "x", CITE)
        with self.assertRaises(SystemExit):
            ach.score_cell(m, "E1", "H1", "X", CITE, by="test")
        with self.assertRaises(SystemExit):
            ach.score_cell(m, "E9", "H1", "C", CITE, by="test")
        with self.assertRaises(SystemExit):
            ach.score_cell(m, "E1", "H9", "C", CITE, by="test")

    def test_check_register(self):
        self.build()
        problems, matrices = ach.check_register(self.reg)
        self.assertEqual(problems, [])
        self.assertIn("ach-t1", matrices)
        self.assertFalse(ach.citation_ok("wiki/no-such-page.md"))


class CliTests(unittest.TestCase):
    def test_cli_round_trip(self):
        tmp = Path(tempfile.mkdtemp())
        reg = tmp / "reg.jsonl"
        tool = SCRIPTS / "wiki_ach.py"

        def run(*argv):
            return subprocess.run(
                [sys.executable, str(tool), "--register", str(reg),
                 *argv], capture_output=True, text=True, timeout=60)

        r = run("create", "--id", "ach-cli", "--question", "Q?",
                "--hypothesis", "yes", "--hypothesis", "no",
                "--by", "test")
        self.assertEqual(r.returncode, 0, r.stderr)
        dup = run("create", "--id", "ach-cli", "--question", "Q?",
                  "--hypothesis", "yes")
        self.assertEqual(dup.returncode, 2)
        r = run("add-evidence", "--id", "ach-cli", "--text", "fact",
                "--cite", CITE)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("score", "--id", "ach-cli", "--evidence", "E1",
                "--hypothesis", "H1", "--value", "I", "--cite", CITE,
                "--by", "test")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("render", "--id", "ach-cli")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Q?", r.stdout)
        self.assertIn("Karvetski", r.stdout)
        r = run("check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run("list")
        self.assertIn("ach-cli", r.stdout)


if __name__ == "__main__":
    unittest.main()
