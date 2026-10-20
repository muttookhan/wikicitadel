"""Tests for scripts/wiki_drift.py — the drift check.

A fixture wiki is built in a temp dir with the real
wiki_drift.py + wiki_decision_gate.py copied in, so ROOT
resolves to the fixture. The fixture pins the behaviours the
build was specified for:

  * check (a) reuses the gate: a present-tense use of a
    superseded form in live prose is a LIVE finding; the
    same form framed historically (a pre-supersession date
    in the window) or in a blockquote is NOT;
  * a hit on a page named by the announcing log entry is
    flagged as the priority case;
  * a register supersession with NO announcing log entry is
    itself a finding (the inverse drift);
  * the dead-term hunt flags a retired phrase in live prose
    but absorbs the correction's own negations and the
    record files, and never scans the drift filings
    themselves;
  * exit codes: findings -> 1 in gate mode, 0 with --report.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REAL_SCRIPTS = Path(__file__).resolve().parent.parent


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


REGISTER = "\n".join([
    json.dumps({"kind": "header", "register": "decisions",
                "version": 1}),
    json.dumps({"kind": "decision", "id": "d1",
                "title": "D1 — Galen's seat",
                "decided_on": "2030-10-13",
                "source": {"page": "wiki/log.md"},
                "superseded_forms": [
                    {"form_id": "d1-reserved",
                     "title": "Galen's seat RESERVED",
                     "superseded_on": "2030-10-16",
                     "superseded_by": "ruling",
                     "match_phrases": ["seat stays reserved",
                                       "seat is reserved"],
                     "aliases": ["galen"],
                     "alias_requires": "reserved"}]}),
    json.dumps({"kind": "decision", "id": "d2",
                "title": "D2 — the portal stays closed",
                "decided_on": "2030-10-13",
                "source": {"page": "wiki/log.md"},
                "superseded_forms": [
                    {"form_id": "d2-closed",
                     "title": "Portal stays CLOSED",
                     "superseded_on": "2030-10-17",
                     "superseded_by": "ruling",
                     "match_phrases": ["portal stays closed"],
                     "aliases": ["portal"],
                     "alias_requires": "closed"}]}),
]) + "\n"

DEAD_TERMS = "\n".join([
    json.dumps({"kind": "header", "register": "dead-terms",
                "version": 1}),
    json.dumps({"kind": "term", "term": "seat form",
                "phrases": ["seat stays reserved"],
                "retired_on": "2030-10-16",
                "origin": "decisions-register: d1",
                "replaced_by": "open", "via": "decision-gate"}),
    json.dumps({"kind": "term",
                "term": "standing always-allow (Drive)",
                "phrases": ["standing always-allow"],
                "retired_on": "2030-10-18",
                "origin": "corrections-ledger",
                "replaced_by": "per-action approval cards",
                "via": "dead-term-hunt"}),
    json.dumps({"kind": "term",
                "term": "15 pattern classes",
                "phrases": ["15 pattern classes"],
                "retired_on": "2030-10-19",
                "origin": "corrections-ledger",
                "replaced_by": "11 pattern classes",
                "via": "dead-term-hunt"}),
]) + "\n"

LOG = """# Log

## [2030-10-13] decision | D1 — Galen's seat reserved

The owner decided: Galen's seat stays reserved.

## [2030-10-16] decision | Owner opens Galen's seat

This REVERSES the decision of 2030-10-13 — the seat is open
now, recorded here and on [[target-page]].
"""


def build_fixture(root):
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for name in ("wiki_drift", "wiki_decision_gate"):
        shutil.copy(REAL_SCRIPTS / f"{name}.py",
                    root / "scripts" / f"{name}.py")
    _write(root / "evaluation" / "decisions-register.jsonl",
           REGISTER)
    _write(root / "evaluation" / "dead-terms.jsonl", DEAD_TERMS)
    _write(root / "wiki" / "log.md", LOG)
    _write(root / "wiki" / "syntheses" / "target-page.md",
           "# Target\n\nGalen's seat stays reserved and no"
           " token is issued.\n")
    _write(root / "wiki" / "syntheses" / "history-page.md",
           "# History\n\nIn the decision of 2030-10-13,"
           " Galen's seat stays reserved, the record said.\n")
    _write(root / "wiki" / "syntheses" / "quote-page.md",
           "# Quote\n\n> Galen's seat stays reserved, the"
           " decision said at the time.\n")
    _write(root / "wiki" / "syntheses" / "portal-page.md",
           "# Portal\n\nThe portal stays closed to everyone"
           " today.\n")
    _write(root / "wiki" / "sources" / "drive-page.md",
           "# Drive\n\nEach move fires its own card. There is"
           " no standing always-allow for Drive moves.\n")
    _write(root / "wiki" / "sources" / "scan-page.md",
           "# Scan\n\nThe gateway scans with 15 pattern"
           " classes at staging.\n")
    _write(root / "wiki" / "rules" / "corrections-ledger.md",
           "# Corrections\n\nThe claim of a standing"
           " always-allow was corrected on the record.\n")
    _write(root / "wiki" / "filings" / "drift-2030-10-19.md",
           "# Drift\n\nYesterday's finding: seat stays"
           " reserved; standing always-allow.\n")
    return root


def load_drift(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_drift_fixture", root / "scripts" / "wiki_drift.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DriftFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = build_fixture(Path(cls.tmp) / "repo")
        cls.drift = load_drift(cls.root)
        cls.result = cls.drift.scan(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestLogVsProse(DriftFixture):
    def test_live_hit_on_plain_present_tense(self):
        files = {h["file"] for h in self.result["prose"]["live"]}
        self.assertIn("wiki/syntheses/target-page.md", files)
        self.assertIn("wiki/syntheses/portal-page.md", files)

    def test_historical_framing_is_not_a_finding(self):
        files = {h["file"] for h in self.result["prose"]["live"]}
        self.assertNotIn("wiki/syntheses/history-page.md", files)
        self.assertNotIn("wiki/syntheses/quote-page.md", files)
        self.assertGreaterEqual(
            self.result["prose"]["historical_count"], 2)

    def test_announcement_names_the_target_page(self):
        hits = [h for h in self.result["prose"]["live"]
                if h["file"] == "wiki/syntheses/target-page.md"]
        self.assertTrue(hits)
        self.assertTrue(
            all(h["named_in_announcement"] for h in hits))

    def test_unannounced_supersession_is_a_finding(self):
        unannounced = {u["form_id"]
                       for u in self.result["prose"]["unannounced"]}
        self.assertEqual(unannounced, {"d2-closed"})

    def test_own_filings_are_not_scanned(self):
        files = {h["file"] for h in self.result["prose"]["live"]}
        self.assertNotIn("wiki/filings/drift-2030-10-19.md",
                         files)


class TestDeadTerms(DriftFixture):
    def test_live_dead_term_found(self):
        hits = self.result["terms"]["findings"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["file"],
                         "wiki/sources/scan-page.md")
        self.assertEqual(hits[0]["term"], "15 pattern classes")

    def test_negation_is_a_corrected_mention(self):
        corrected = {h["file"]
                     for h in self.result["terms"]["corrected"]}
        self.assertIn("wiki/sources/drive-page.md", corrected)

    def test_record_pages_are_corrected_mentions(self):
        # The corrections ledger recounts the retired phrase
        # as the record of the correction (H1: the file is
        # the record) — a mention, never a finding.
        corrected = {h["file"]
                     for h in self.result["terms"]["corrected"]}
        self.assertIn("wiki/rules/corrections-ledger.md",
                      corrected)
        findings = {h["file"]
                    for h in self.result["terms"]["findings"]}
        self.assertNotIn("wiki/rules/corrections-ledger.md",
                         findings)

    def test_gate_routed_terms_not_double_hunted(self):
        self.assertEqual(self.result["terms"]["terms_hunted"], 2)
        self.assertEqual(self.result["terms"]["terms_total"], 3)
        terms = {h["term"]
                 for h in self.result["terms"]["findings"]}
        self.assertNotIn("seat form", terms)

    def test_own_filings_excluded_from_hunt(self):
        files = {h["file"] for h
                 in self.result["terms"]["findings"]}
        files |= {h["file"] for h
                  in self.result["terms"]["corrected"]}
        self.assertNotIn("wiki/filings/drift-2030-10-19.md",
                         files)


class TestCliAndSection(DriftFixture):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable,
             str(self.root / "scripts" / "wiki_drift.py"),
             *args],
            capture_output=True, text=True)

    def test_gate_mode_exits_1_on_findings(self):
        self.assertEqual(self._run().returncode, 1)

    def test_report_mode_exits_0(self):
        proc = self._run("--report")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("DRIFT", proc.stdout)

    def test_section_is_lanes_shaped(self):
        section = self.drift.render_section(
            self.result, "2030-10-20")
        self.assertTrue(section.startswith("## Drift —"))
        self.assertIn("dead-term", section)


if __name__ == "__main__":
    unittest.main()
