#!/usr/bin/env python3
"""Tests for scripts/wiki_cases.py — Contradiction Cases and
the adjudication queue (the build).

The heart of the build is the TIME-AWARE classification: a
Case opens only when two claims about the same fact cannot
both be true at the same as-of time. Same fact at different
times is a supersession, never a Case (the wave-3 warning:
naive contradiction detection elsewhere was 99.7% false
positives, nearly all same-fact-different-time).

Builds a fixture wiki in a temp dir (the real script copied
in, so ROOT resolves to the fixture) and drives the CLI plus
the classifier directly.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_cases_module(script_path):
    spec = importlib.util.spec_from_file_location(
        "wiki_cases_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def claim(fact="f", as_of="2030-10-20", page="wiki/x.md",
          text="claim"):
    return {"fact": fact, "page": page, "text": text,
            "as_of": as_of}


class ClassifyTests(unittest.TestCase):
    """The classifier needs no fixture — load the real script."""

    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases_module(SCRIPTS / "wiki_cases.py")

    def test_same_fact_same_time_is_a_contradiction(self):
        kind, _ = self.cases.classify(claim(), claim(page="wiki/y.md"))
        self.assertEqual(kind, "contradiction")

    def test_same_fact_different_time_is_supersession(self):
        kind, reason = self.cases.classify(
            claim(as_of="2030-10-18"),
            claim(as_of="2030-10-20", page="wiki/y.md"))
        self.assertEqual(kind, "supersession")
        self.assertIn("supersedes", reason)

    def test_single_claim_is_no_opposing_claim(self):
        kind, _ = self.cases.classify(claim(), None)
        self.assertEqual(kind, "no-opposing-claim")

    def test_different_fact_is_not_a_conflict(self):
        kind, _ = self.cases.classify(
            claim(fact="a"), claim(fact="b", page="wiki/y.md"))
        self.assertEqual(kind, "different-fact")

    def test_missing_as_of_is_indeterminate(self):
        kind, _ = self.cases.classify(
            claim(as_of=None), claim(page="wiki/y.md"))
        self.assertEqual(kind, "indeterminate")


IDEAS = """---
title: Ideas fixture
type: synthesis
created: 2030-10-19
updated: 2030-10-20
sources: []
tags: [ideas]
---

# Ideas

## Waiting for your call

- **Fixture idea one** — a test idea — Agent, 2030-10-20
- **Fixture idea two** — another — Agent, 2030-10-19

## Approved

- **Old approved thing** — built — 2030-10-19

## Disapproved

*(none yet)*
"""


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        shutil.copy(SCRIPTS / "wiki_cases.py",
                    self.tmp / "scripts" / "wiki_cases.py")
        (self.tmp / "wiki" / "filings").mkdir(parents=True)
        (self.tmp / "wiki" / "ideas.md").write_text(
            IDEAS, encoding="utf-8")
        staging = self.tmp / "staging" / "proposed"
        staging.mkdir(parents=True)
        (staging / "prop-aaaa.json").write_text(json.dumps({
            "proposal_id": "prop-aaaa", "state": "draft",
            "submitted_at": "2030-10-13T00:00:00Z",
            "submitted_by": "fixture",
            "target_path": "wiki/x.md"}), encoding="utf-8")
        (staging / "prop-bbbb.json").write_text(json.dumps({
            "proposal_id": "prop-bbbb", "state": "draft",
            "submitted_at": "2030-10-12T00:00:00Z",
            "submitted_by": "fixture",
            "target_path": "wiki/y.md",
            "promoted_at": "2030-10-13T00:00:00Z"}),
            encoding="utf-8")
        self.script = self.tmp / "scripts" / "wiki_cases.py"

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.script), *argv],
            capture_output=True, text=True)

    def open_pair(self, as_of_a, as_of_b, fact="fixture-fact"):
        return self.run_cli(
            "open", "--fact", fact,
            "--page-a", "wiki/a.md", "--text-a", "version A",
            "--as-of-a", as_of_a,
            "--page-b", "wiki/b.md", "--text-b", "version B",
            "--as-of-b", as_of_b, "--date", "2030-10-20")

    def register_lines(self):
        path = self.tmp / "evaluation" / "contradiction-cases.jsonl"
        return [json.loads(l) for l in
                path.read_text(encoding="utf-8").splitlines() if l]

    def test_same_time_pair_opens_a_case(self):
        r = self.open_pair("2030-10-20", "2030-10-20")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("classification=contradiction status=open",
                      r.stdout)
        r = self.run_cli("list")
        self.assertIn("case-0001", r.stdout)

    def test_different_time_pair_opens_no_case(self):
        r = self.open_pair("2030-10-18", "2030-10-20")
        self.assertIn("classification=supersession "
                      "status=closed-supersession", r.stdout)
        r = self.run_cli("list")
        self.assertIn("no open Cases", r.stdout)
        # ...but the record exists and says what it is
        r = self.run_cli("list", "--all")
        self.assertIn("closed-supersession", r.stdout)

    def test_single_claim_opens_no_case(self):
        r = self.run_cli("open", "--fact", "solo",
                         "--page-a", "wiki/a.md",
                         "--text-a", "multiply supported",
                         "--as-of-a", "2030-10-18",
                         "--date", "2030-10-20")
        self.assertIn("no-opposing-claim", r.stdout)
        r = self.run_cli("list")
        self.assertIn("no open Cases", r.stdout)

    def test_rule_closes_case_and_record_stays(self):
        self.open_pair("2030-10-20", "2030-10-20")
        r = self.run_cli("rule", "--case", "case-0001",
                         "--ruling", "A stands; B was wrong.",
                         "--winner", "a", "--date", "2030-10-21")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("list")
        self.assertIn("no open Cases", r.stdout)
        r = self.run_cli("list", "--all")
        self.assertIn("closed-ruled", r.stdout)
        self.assertIn("A stands; B was wrong.", r.stdout)
        kinds = [e["kind"] for e in self.register_lines()]
        self.assertEqual(kinds, ["header", "case", "ruling"])
        # a closed Case cannot be ruled on twice
        r = self.run_cli("rule", "--case", "case-0001",
                         "--ruling", "again")
        self.assertEqual(r.returncode, 2)

    def test_queue_oldest_first_and_promoted_excluded(self):
        self.open_pair("2030-10-20", "2030-10-20")
        out = self.tmp / "queue.md"
        r = self.run_cli("queue", "--date", "2030-10-20",
                         "--out", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("prop-aaaa", text)
        self.assertNotIn("prop-bbbb", text)  # already promoted
        self.assertNotIn("Old approved thing", text)
        lines = [l for l in text.splitlines()
                 if l[:3].strip().rstrip(".").isdigit()]
        self.assertEqual(len(lines), 4)  # proposal, case, 2 ideas
        # oldest first: 2030-10-13 proposal, then 2030-10-19
        # idea, then the two 2030-10-20 items
        self.assertIn("2030-10-13", lines[0])
        self.assertIn("prop-aaaa", lines[0])
        self.assertIn("2030-10-19", lines[1])
        self.assertIn("Fixture idea two", lines[1])


if __name__ == "__main__":
    unittest.main()
