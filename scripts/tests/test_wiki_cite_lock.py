#!/usr/bin/env python3
"""Tests for scripts/wiki_cite_lock.py — the citation integrity
pack (lockfile + source manifest + quote verification). Builds a
fixture wiki in a temp dir (the real scripts copied in, so ROOT
resolves to the fixture) and drives the CLI.

The discrimination that matters: MOVED (same cited lines, new
range) vs CHANGED (cited content differs) vs MISSING (source or
lines gone) — plus the manifest flagging every citation into a
changed source, and quote verification catching a misquote.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

SOURCE_LINES = [
    "Fixture source title",
    "alpha bravo charlie",
    "delta echo foxtrot",
    "golf hotel india",
    "juliet kilo lima",
    'The engineer said "the server hums quietly" during rounds.',
]

PAGE = """---
title: Fixture page
type: source
created: 2030-10-20
updated: 2030-10-20
sources:
  - raw/sources/fixture-source.md
tags: [fixture]
---

Alpha claim sentence.^[cite: raw/sources/fixture-source.md#L2-L3]

The report said "the server hums quietly" in the log.^[cite: raw/sources/fixture-source.md#L6]
"""


class CiteLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_cite_lock.py", "wiki_observe.py",
                     "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        (self.tmp / "raw" / "sources").mkdir(parents=True)
        (self.tmp / "evaluation").mkdir()
        self.source = self.tmp / "raw" / "sources" / "fixture-source.md"
        self.page = self.tmp / "wiki" / "sources" / "fixture-page.md"
        self.write_source(SOURCE_LINES)
        self.page.write_text(PAGE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_source(self, lines):
        self.source.write_text("\n".join(lines) + "\n",
                               encoding="utf-8")

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / "wiki_cite_lock.py"), *argv],
            capture_output=True, text=True)

    def build(self):
        proc = self.run_cli("build")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def lockfile(self):
        return json.loads(
            (self.tmp / "evaluation" / "citation-lockfile.json")
            .read_text(encoding="utf-8"))

    def load_module(self):
        spec = importlib.util.spec_from_file_location(
            "fixture_cite_lock",
            self.tmp / "scripts" / "wiki_cite_lock.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # -- build + clean check -------------------------------------

    def test_build_locks_everything_and_check_passes(self):
        self.build()
        lock = self.lockfile()
        self.assertEqual(lock["coverage"]["citations"], 2)
        self.assertEqual(lock["coverage"]["sources_registered"], 1)
        rows = (self.tmp / "evaluation" / "source-manifest.jsonl") \
            .read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0])
        self.assertEqual(row["path"], "raw/sources/fixture-source.md")
        self.assertEqual(
            row["sha256"],
            hashlib.sha256(self.source.read_bytes()).hexdigest())
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("OK 2", proc.stdout)
        self.assertIn("Result: PASS", proc.stdout)

    def test_strong_mode_groups_by_source(self):
        self.build()
        proc = self.run_cli("check", "--strong")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("== raw/sources/fixture-source.md", proc.stdout)
        self.assertIn("[OK] c0001", proc.stdout)

    # -- MOVED vs CHANGED vs MISSING ------------------------------

    def test_moved_when_lines_shift(self):
        self.build()
        self.write_source(["inserted header line"] + SOURCE_LINES)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[MOVED] c0001", proc.stdout)
        self.assertIn("L3-L4", proc.stdout)
        self.assertIn("[MOVED] c0002", proc.stdout)
        self.assertIn("L7-L7", proc.stdout)
        # The file's bytes changed, so the manifest flags both.
        self.assertIn("[MANIFEST CHANGED]", proc.stdout)

    def test_changed_when_cited_text_is_edited(self):
        self.build()
        lines = list(SOURCE_LINES)
        lines[1] = "alpha bravo rewritten"
        self.write_source(lines)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[CHANGED] c0001", proc.stdout)
        # The untouched citation still verifies OK.
        self.assertIn("OK 1", proc.stdout)
        self.assertNotIn("[CHANGED] c0002", proc.stdout)
        self.assertNotIn("[MOVED]", proc.stdout)

    def test_missing_when_source_deleted(self):
        self.build()
        self.source.unlink()
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("MISSING 2", proc.stdout)
        self.assertIn("[MANIFEST MISSING]", proc.stdout)

    def test_missing_when_lines_are_gone(self):
        self.build()
        self.write_source(SOURCE_LINES[:1])
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[MISSING] c0001", proc.stdout)
        self.assertIn("[MISSING] c0002", proc.stdout)

    def test_unlocked_marker_is_reported(self):
        self.build()
        text = self.page.read_text(encoding="utf-8")
        self.page.write_text(
            text + "\nNew claim.^[cite: raw/sources/"
                   "fixture-source.md#L4]\n",
            encoding="utf-8")
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[UNLOCKED]", proc.stdout)

    # -- dual-anchored selectors --------------------------------

    def test_build_locks_dual_anchor_selectors(self):
        self.build()
        lock = self.lockfile()
        self.assertEqual(lock["lockfile_version"], 2)
        self.assertEqual(lock["coverage"]["selectors"], 2)
        first = lock["citations"][0]
        sel = first["selector"]
        self.assertEqual(sel["type"], "TextQuoteSelector")
        self.assertEqual(sel["exact"],
                         "alpha bravo charlie\ndelta echo foxtrot")
        self.assertEqual(sel["prefix"], "Fixture source title\n")
        self.assertTrue(sel["suffix"].startswith("\ngolf hotel"))
        # Both anchors verify on the untouched corpus.
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_default_converter_is_unknown_legacy(self):
        self.build()
        rows = (self.tmp / "evaluation" / "source-manifest.jsonl") \
            .read_text(encoding="utf-8").strip().splitlines()
        row = json.loads(rows[0])
        self.assertEqual(row["converter"],
                         {"kind": "unknown-legacy"})
        lock = self.lockfile()
        self.assertEqual(lock["coverage"]["converter_recorded"], 0)
        self.assertEqual(
            lock["coverage"]["converter_unknown_legacy"], 1)
        proc = self.run_cli("check", "--strong")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("unknown-legacy", proc.stdout)
        self.assertIn("quote anchor: AT_RANGE", proc.stdout)

    def test_moved_via_quote_anchor_when_lines_reflow(self):
        # The case dual anchoring exists for: the passage's words
        # survive but its line breaks do not (a re-conversion),
        # and it sits at a new range. The per-line hashes find
        # nothing; the quote anchor still resolves.
        self.build()
        self.write_source([
            "Fixture source title",
            "inserted header line",
            "alpha bravo",
            "charlie delta echo foxtrot",
            "golf hotel india",
            "juliet kilo lima",
            'The engineer said "the server hums quietly"'
            " during rounds.",
        ])
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[MOVED] c0001", proc.stdout)
        self.assertIn("quote anchor", proc.stdout)
        self.assertIn("L3-L4", proc.stdout)

    def test_changed_when_both_anchors_fail(self):
        self.build()
        lines = list(SOURCE_LINES)
        lines[1] = "completely different words now"
        lines[2] = "nothing alike at all"
        self.write_source(lines)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[CHANGED] c0001", proc.stdout)
        self.assertIn("AMBIGUOUS 0", proc.stdout)
        self.assertNotIn("[AMBIGUOUS]", proc.stdout)

    def test_whitespace_drift_changed_but_quote_anchor_resolves(self):
        # Trailing space inside a cited line: the line hashes
        # fail, the words are untouched. The disagreement is
        # reported as itself — CHANGED, with the quote anchor's
        # continued resolution named in the detail.
        self.build()
        lines = list(SOURCE_LINES)
        lines[1] = "alpha bravo charlie "
        self.write_source(lines)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[CHANGED] c0001", proc.stdout)
        self.assertIn("quote anchor still resolves", proc.stdout)

    def _write_duplicate_source(self, second_context):
        """A source whose cited passage occurs twice, each time
        between long context lines; `second_context` is the
        context line used around the second occurrence."""
        ctx = "context context context context line"
        lines = [
            "title line",
            ctx,
            "alpha bravo charlie",
            "delta echo foxtrot",
            ctx,
            second_context,
            "alpha bravo charlie",
            "delta echo foxtrot",
            ctx,
        ]
        self.write_source(lines)
        return lines

    def _reflow_both(self, lines):
        out = []
        for ln in lines:
            if ln == "alpha bravo charlie":
                out += ["alpha bravo", "charlie"]
            else:
                out.append(ln)
        self.write_source(out)

    def test_ambiguous_quote_is_reported_honestly(self):
        # The passage occurs twice with identical prefix/suffix
        # context; after a reflow the line anchor pins neither
        # copy and the context cannot either -> AMBIGUOUS, not
        # a guessed resolution.
        lines = self._write_duplicate_source(
            "context context context context line")
        self.page.write_text(PAGE.replace("#L2-L3", "#L3-L4")
                             .replace("#L6", "#L3"),
                             encoding="utf-8")
        self.build()
        self._reflow_both(lines)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[AMBIGUOUS] c0001", proc.stdout)
        self.assertIn("cannot disambiguate", proc.stdout)

    def test_context_disambiguates_a_duplicate_quote(self):
        # Same duplication, but the second occurrence's context
        # differs: the quote anchor + context resolve uniquely
        # to the cited copy's new range -> MOVED, not AMBIGUOUS.
        lines = self._write_duplicate_source(
            "other other other other other line here")
        self.page.write_text(PAGE.replace("#L2-L3", "#L7-L8")
                             .replace("#L6", "#L3"),
                             encoding="utf-8")
        self.build()
        self._reflow_both(lines)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[MOVED] c0001", proc.stdout)
        self.assertIn("quote anchor", proc.stdout)
        self.assertNotIn("[AMBIGUOUS]", proc.stdout)

    # -- quote verification ----------------------------------------

    def test_quote_verifies_then_diverges_on_misquote(self):
        module = self.load_module()
        report = module.quote_report()
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["verified"], 1)
        self.assertEqual(report["divergences"], [])
        text = self.page.read_text(encoding="utf-8")
        self.page.write_text(
            text.replace("the server hums quietly",
                         "the server hums loudly"),
            encoding="utf-8")
        report = module.quote_report()
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["verified"], 0)
        self.assertEqual(len(report["divergences"]), 1)
        self.assertIn("diverges after", report["divergences"][0]
                      ["divergence"])

    def test_quote_diverges_when_source_wording_changes(self):
        module = self.load_module()
        lines = list(SOURCE_LINES)
        lines[5] = 'The engineer said "the server hums softly" today.'
        self.write_source(lines)
        report = module.quote_report()
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["verified"], 0)


FAKE_CONVERTER_V1 = "# fixture converter, version 1\n"
FAKE_CONVERTER_V2 = "# fixture converter, version 2 — changed\n"


class ConverterIdentityTests(unittest.TestCase):
    """Item 8: the lockfile records the converter identity a
    converted source was produced under (from its ingest
    sidecar), and a later converter change re-flags its
    citations instead of silently passing them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_cite_lock.py", "wiki_observe.py",
                     "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        (self.tmp / "raw" / "sources").mkdir(parents=True)
        (self.tmp / "evaluation").mkdir()
        self.source = self.tmp / "raw" / "sources" / "fixture-source.md"
        self.source.write_text("\n".join(SOURCE_LINES) + "\n",
                               encoding="utf-8")
        page = self.tmp / "wiki" / "sources" / "fixture-page.md"
        page.write_text(PAGE, encoding="utf-8")
        self.converter = self.tmp / "scripts" / "wiki_convert.py"
        self.sidecar = Path(str(self.source) + ".ingest.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / "wiki_cite_lock.py"), *argv],
            capture_output=True, text=True)

    def write_converter(self, text):
        self.converter.write_text(text, encoding="utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def write_sidecar(self, script_sha256):
        record = {
            "source": "/originals/fixture-source.md",
            "sha256": "0" * 64,
            "trust_tier": "untrusted",
            "sanitiser": {"verdict": "clean", "findings": []},
        }
        if script_sha256 is not None:
            record["converter"] = {
                "tool": "wiki_convert.py",
                "script_sha256": script_sha256,
                "sanitizer_sha256": None,
                "format": "md",
            }
        self.sidecar.write_text(json.dumps(record),
                                encoding="utf-8")

    def manifest_row(self):
        rows = (self.tmp / "evaluation" / "source-manifest.jsonl") \
            .read_text(encoding="utf-8").strip().splitlines()
        return json.loads(rows[0])

    def test_identity_recorded_and_check_passes(self):
        sha = self.write_converter(FAKE_CONVERTER_V1)
        self.write_sidecar(sha)
        proc = self.run_cli("build")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("converter identity: 1 of 1", proc.stdout)
        conv = self.manifest_row()["converter"]
        self.assertEqual(conv["kind"], "wiki_convert")
        self.assertEqual(conv["script_sha256"], sha)
        self.assertEqual(conv["format"], "md")
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Result: PASS", proc.stdout)

    def test_converter_change_reflags_citations(self):
        sha = self.write_converter(FAKE_CONVERTER_V1)
        self.write_sidecar(sha)
        self.assertEqual(self.run_cli("build").returncode, 0)
        self.write_converter(FAKE_CONVERTER_V2)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("[CONVERTER CHANGED]", proc.stdout)
        self.assertIn("c0001", proc.stdout)
        proc = self.run_cli("check", "--strong")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("converter: recorded wiki_convert.py",
                      proc.stdout)
        self.assertIn("→ CHANGED", proc.stdout)

    def test_sidecar_without_converter_record_is_unrecorded(self):
        # A sidecar from before converter recording: the kind is
        # determinable (wiki_convert produced it) but no script
        # identity was recorded — check must not invent one, and
        # must not fail on the absence.
        self.write_converter(FAKE_CONVERTER_V1)
        self.write_sidecar(None)
        self.assertEqual(self.run_cli("build").returncode, 0)
        conv = self.manifest_row()["converter"]
        self.assertEqual(conv["kind"], "wiki_convert")
        self.assertIsNone(conv["script_sha256"])
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Result: PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
