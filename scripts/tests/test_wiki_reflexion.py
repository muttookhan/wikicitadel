#!/usr/bin/env python3
"""Pins wiki_reflexion (Marathon R5 lane BB; Shinn et al.
Reflexion pattern): notes are composed deterministically from
a fixed cause-class vocabulary and a fixed do-differently
table; appending is explicit (--apply), append-only, and
dry-run by default; the failure scan reads the wiring points
(ask-door qa log, ingest queue, post-mortems) and writes
nothing; an unknown cause class is refused, never improvised.

Run:  python3 -m unittest discover -s scripts/tests
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wiki_reflexion", SCRIPTS / "wiki_reflexion.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PAGE = """---
title: Harbour Lights
type: source
created: 2026-01-15
updated: 2026-01-15
sources: [raw/sources/harbour.md]
tags: [fixture]
---

The harbour light flashes twice every ten seconds at night.
"""


class TestReflexion(unittest.TestCase):
    def test_note_shape_and_fixed_table(self):
        note = m.make_note("Ingest of harbour.md failed",
                           "source-unreadable",
                           "evaluation/ingest-queue.jsonl#4",
                           "harbour", "2026-10-21")
        self.assertIn("[2026-10-21] reflexion | harbour", note)
        self.assertIn("Cause class: source-unreadable", note)
        self.assertIn(m.DO_DIFFERENTLY["source-unreadable"], note)
        # deterministic
        self.assertEqual(note, m.make_note(
            "Ingest of harbour.md failed", "source-unreadable",
            "evaluation/ingest-queue.jsonl#4", "harbour",
            "2026-10-21"))

    def test_unknown_cause_class_refused(self):
        with self.assertRaises(m.ReflexionError):
            m.make_note("x", "bad-luck", "e", "s", "2026-10-21")
        with self.assertRaises(SystemExit) as ctx:
            m.main(["draft", "--what-failed", "x",
                    "--cause-class", "bad-luck", "--evidence", "e"])
        self.assertEqual(ctx.exception.code, 2)

    def test_append_creates_section_and_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki").mkdir()
            page = root / "wiki" / "harbour.md"
            page.write_text(PAGE)
            note = m.make_note("QA abstained on the harbour page",
                               "missing-evidence",
                               "wiki/access/qa-2026.jsonl#2",
                               "harbour", "2026-10-21")
            once = m.append_note(PAGE, note)
            self.assertTrue(once.startswith(PAGE))
            self.assertIn("## Reflection notes", once)
            self.assertIn(note, once)
            note2 = m.make_note("Second failure on the page",
                                "citation-drift",
                                "evaluation/citation-lockfile.json",
                                "harbour", "2026-10-22")
            twice = m.append_note(once, note2)
            self.assertIn(note, twice)
            self.assertIn(note2, twice)
            self.assertEqual(twice.count("## Reflection notes"), 1)
            self.assertLess(twice.index(note), twice.index(note2))

    def test_cli_dry_run_writes_nothing_apply_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki").mkdir()
            page = root / "wiki" / "harbour.md"
            page.write_text(PAGE)
            base = ["--root", str(root), "append",
                    "--page", "wiki/harbour.md",
                    "--what-failed", "Ingest failed on the page",
                    "--cause-class", "transport-failure",
                    "--evidence", "evaluation/ingest-queue.jsonl#1",
                    "--date", "2026-10-21"]
            self.assertEqual(m.main(base), 0)
            self.assertEqual(page.read_text(), PAGE)  # dry-run
            self.assertEqual(m.main(base + ["--apply"]), 0)
            self.assertIn("reflexion | harbour", page.read_text())
            self.assertIn("Cause class: transport-failure",
                          page.read_text())

    def test_scan_reads_wiring_points_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "access").mkdir(parents=True)
            (root / "evaluation").mkdir()
            (root / "wiki" / "access" / "qa-2026.jsonl").write_text(
                json.dumps({"id": "q_1", "status": "answered"}) + "\n"
                + json.dumps({"id": "q_2", "status": "abstained",
                              "abstention_reason": "no evidence in "
                              "the corpus"}) + "\n")
            (root / "evaluation" / "ingest-queue.jsonl").write_text(
                json.dumps({"kind": "enqueued", "id": "i1"}) + "\n"
                + json.dumps({"kind": "failed", "id": "i2",
                              "reason": "source unreadable: bad pdf "
                              "extraction"}) + "\n")
            (root / "evaluation" / "post-mortems.jsonl").write_text(
                json.dumps({"id": "PM-1", "title": "Scoped too "
                            "narrowly", "root_cause_class": "scope"})
                + "\n")
            before = {p: p.read_bytes() for p in root.rglob("*")
                      if p.is_file()}
            report = m.scan_failures(root)
            self.assertEqual(report["count"], 3)
            self.assertEqual(report["writes"], 0)
            by_wiring = {f["wiring"]: f for f in report["failures"]}
            self.assertEqual(by_wiring["ask-door"]["cause_class"],
                             "missing-evidence")
            self.assertEqual(by_wiring["ingest-queue"]["cause_class"],
                             "source-unreadable")
            self.assertEqual(by_wiring["post-mortems"]["cause_class"],
                             "scope-error")
            after = {p: p.read_bytes() for p in root.rglob("*")
                     if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
