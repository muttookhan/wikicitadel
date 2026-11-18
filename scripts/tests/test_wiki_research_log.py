#!/usr/bin/env python3
"""Tests for scripts/wiki_research_log.py — the append-only
research log (consolidated-queue item 13: genealogy proof bar).

The log's discipline in code: a result is exactly one of
found / not-found / door-failed; a door failure can never be
recorded as a negative finding; appending never rewrites an
existing line.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rlog = load("wiki_research_log")

ENTRY = {
    "date": "2030-10-20",
    "claim": "Bates (1989) primary text is reachable",
    "page": "raw/sources/example.md (§2)",
    "query": "Bates 1989 berrypicking PDF",
    "doors": ["author's faculty page", "direct fetch"],
    "result": "found",
    "notes": "Located on the author's own page.",
}


class AppendTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_first_append_creates_header_then_entry(self):
        rlog.append_entry(self.root, dict(ENTRY))
        lines = (self.root / "evaluation/research-log.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["kind"], "header")
        entry = json.loads(lines[1])
        self.assertEqual(entry["kind"], "search")
        self.assertEqual(entry["result"], "found")
        self.assertEqual(entry["doors"],
                         ["author's faculty page", "direct fetch"])

    def test_append_is_append_only(self):
        rlog.append_entry(self.root, dict(ENTRY))
        path = self.root / "evaluation/research-log.jsonl"
        before = path.read_text(encoding="utf-8")
        second = dict(ENTRY, claim="another claim", result="not-found")
        rlog.append_entry(self.root, second)
        after = path.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        self.assertEqual(len(after.splitlines()), 3)

    def test_bad_result_class_refused(self):
        with self.assertRaises(ValueError):
            rlog.append_entry(self.root, dict(ENTRY, result="missing"))

    def test_door_failed_is_a_distinct_class(self):
        rec = rlog.append_entry(
            self.root, dict(ENTRY, result="door-failed"))
        self.assertEqual(rec["result"], "door-failed")

    def test_empty_doors_refused(self):
        with self.assertRaises(ValueError):
            rlog.append_entry(self.root, dict(ENTRY, doors=[]))

    def test_missing_claim_refused(self):
        with self.assertRaises(ValueError):
            rlog.append_entry(self.root, dict(ENTRY, claim=""))


class ListTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        rlog.append_entry(self.root, dict(ENTRY))
        rlog.append_entry(self.root, dict(
            ENTRY, claim="GitLab interior via ecosyste.ms",
            result="door-failed"))
        rlog.append_entry(self.root, dict(
            ENTRY, claim="Bates follow-up: the 2002 restatement",
            result="not-found"))

    def test_list_all_skips_header(self):
        self.assertEqual(len(rlog.list_entries(self.root)), 3)

    def test_filter_by_claim_substring(self):
        hits = rlog.list_entries(self.root, claim_substr="bates")
        self.assertEqual(len(hits), 2)

    def test_filter_by_result(self):
        hits = rlog.list_entries(self.root, result="door-failed")
        self.assertEqual(len(hits), 1)
        self.assertIn("ecosyste", hits[0]["claim"])


if __name__ == "__main__":
    unittest.main()
