#!/usr/bin/env python3
"""Tests for scripts/wiki_ocr_queue.py — the OCR verification
queue (item 54) — plus the extraction block scripts/
wiki_convert.py now writes into every ingest sidecar.

The CLI is driven against a fixture repo in a temp dir (the
real scripts copied in, so the tool's ROOT resolves to the
fixture), mirroring test_wiki_queues.py. The sidecar tests
load the real wiki_convert.py by path, the way
test_wiki_sanitize_convert.py does, and run the real format
watch over a sidecar the converter wrote — the Phase-3 reader
must keep reading sidecars now that they carry `extraction`.

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
REPO = SCRIPTS.parent
NEEDS = ("wiki_ocr_queue.py", "wiki_validate.py")

PLAN_PAGE = """---
title: Plan compiled from a scan
type: source
created: 2030-10-20
sources:
  - raw/sources/scan.pdf
---

A claim resting on the scanned plan.
"""

PERSON_PAGE = """---
title: Person
type: entity
created: 2030-10-20
sources: []
---

The plan says so.^[cite: raw/sources/scan.pdf#L1-L9]
"""


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OcrFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        for name in NEEDS:
            shutil.copy(SCRIPTS / name, self.root / "scripts")
        (self.root / "raw" / "sources").mkdir(parents=True)
        (self.root / "raw" / "sources" / "scan.pdf").write_bytes(
            b"%PDF-1.4 fixture")
        (self.root / "raw" / "sources" / "corrected.txt").write_text(
            "corrected reading\n", encoding="utf-8")
        (self.root / "wiki" / "sources").mkdir(parents=True)
        (self.root / "wiki" / "entities").mkdir(parents=True)
        (self.root / "evaluation").mkdir(parents=True)
        self.tool = self.root / "scripts" / "wiki_ocr_queue.py"
        self.register = self.root / "evaluation" / "ocr-queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tool), *argv],
            capture_output=True, text=True)

    def enqueue(self, units, method="ocr"):
        units_file = self.root / "units.json"
        units_file.write_text(json.dumps(units), encoding="utf-8")
        return self.run_cli(
            "enqueue", "--source", "raw/sources/scan.pdf",
            "--method", method, "--tool", "fixture-ocr",
            "--units", str(units_file), "--date", "2030-10-20")

    def list_json(self):
        proc = self.run_cli("list", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class EnqueueTests(OcrFixture):
    def test_threshold_split(self):
        proc = self.enqueue([
            {"unit": "w1", "locator": {"page": 1},
             "text": "clear", "confidence": 0.95},
            {"unit": "w2", "locator": {"page": 1},
             "text": "edge", "confidence": 0.90},
            {"unit": "w3", "locator": {"page": 1},
             "text": "faint", "confidence": 0.899},
            {"unit": "w4", "locator": {"page": 2},
             "text": "smudged", "confidence": 0.40},
            {"unit": "w5", "locator": {"page": 2},
             "text": "unrated", "confidence": "unknown"},
        ])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ocr-0001", proc.stdout)
        entry = self.list_json()["entries"][0]
        self.assertEqual(entry["counts"],
                         {"above-threshold": 2, "open": 3})
        # no sensitivity register in the fixture: the class is
        # recorded as unclassified, never as a clearance
        self.assertEqual(entry["sensitivity"], "unclassified")

    def test_missing_source_refused(self):
        proc = self.run_cli(
            "enqueue", "--source", "raw/sources/ghost.pdf",
            "--method", "ocr")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(self.register.exists())

    def test_unreported_confidence_is_unknown_not_invented(self):
        proc = self.enqueue([
            {"unit": "w1", "locator": {"page": 1},
             "text": "word"}])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.list_json()["entries"][0]
        self.assertEqual(entry["counts"], {"open": 1})

    def test_confidence_out_of_range_refused(self):
        proc = self.enqueue([
            {"unit": "w1", "locator": {"page": 1},
             "text": "word", "confidence": 1.5}])
        self.assertEqual(proc.returncode, 2)
        proc = self.enqueue([
            {"unit": "w1", "locator": {"page": 1},
             "text": "word", "confidence": "high"}])
        self.assertEqual(proc.returncode, 2)


class CheckTests(OcrFixture):
    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "sources" / "plan.md").write_text(
            PLAN_PAGE, encoding="utf-8")
        (self.root / "wiki" / "entities" / "person.md").write_text(
            PERSON_PAGE, encoding="utf-8")
        proc = self.enqueue([
            {"unit": "p1", "locator": {"page": 1},
             "confidence": "unknown"}])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_check_flags_frontmatter_and_cite_marker_pages(self):
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("wiki/sources/plan.md", proc.stdout)
        self.assertIn("wiki/entities/person.md", proc.stdout)
        self.assertIn("UNVERIFIED", proc.stdout)

    def test_check_json_shape(self):
        proc = self.run_cli("check", "--json")
        self.assertEqual(proc.returncode, 1)
        report = json.loads(proc.stdout)
        self.assertEqual(report["open_units"], 1)
        self.assertEqual(len(report["flags"]), 1)
        self.assertEqual(sorted(report["flags"][0]["pages"]),
                         ["wiki/entities/person.md",
                          "wiki/sources/plan.md"])

    def test_verify_all_clears_the_flag(self):
        proc = self.run_cli("verify", "ocr-0001", "--by",
                            "owner", "--date", "2030-10-20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TransitionTests(OcrFixture):
    def setUp(self):
        super().setUp()
        proc = self.enqueue([
            {"unit": "w1", "locator": {"page": 1},
             "text": "Zanzibar", "confidence": 0.52},
            {"unit": "w2", "locator": {"page": 1},
             "text": "blur", "confidence": 0.31}])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_verify_kept_is_a_recorded_outcome(self):
        proc = self.run_cli("verify", "ocr-0001", "--unit", "w1",
                            "--by", "agent", "--outcome", "kept",
                            "--date", "2030-10-20",
                            "--note", "checked against the "
                                      "original; kept as-is")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.list_json()["entries"][0]
        self.assertEqual(entry["counts"],
                         {"verified-kept": 1, "open": 1})

    def test_resolved_unit_cannot_be_reverified(self):
        self.run_cli("verify", "ocr-0001", "--unit", "w1",
                     "--by", "agent")
        proc = self.run_cli("verify", "ocr-0001", "--unit", "w1",
                            "--by", "agent")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("already verified-confirmed",
                      proc.stderr)

    def test_transitions_are_append_only(self):
        before = self.register.read_bytes()
        self.run_cli("verify", "ocr-0001", "--unit", "w1",
                     "--by", "agent")
        after = self.register.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(
            len(after.decode().strip().splitlines()),
            len(before.decode().strip().splitlines()) + 1)

    def test_reject_needs_corrected_text_location(self):
        proc = self.run_cli("reject", "ocr-0001", "--unit", "w2",
                            "--by", "agent")
        self.assertEqual(proc.returncode, 2)
        proc = self.run_cli(
            "reject", "ocr-0001", "--unit", "w2", "--by", "agent",
            "--corrected-text-at", "raw/sources/missing.txt")
        self.assertEqual(proc.returncode, 2)

    def test_reject_records_corrected_location(self):
        proc = self.run_cli(
            "reject", "ocr-0001", "--unit", "w2", "--by", "agent",
            "--corrected-text-at", "raw/sources/corrected.txt",
            "--date", "2030-10-20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.list_json()["entries"][0]
        self.assertEqual(entry["counts"].get("rejected"), 1)
        events = [json.loads(l) for l in
                  self.register.read_text().splitlines() if l]
        rejected = [e for e in events
                    if e.get("kind") == "rejected"]
        self.assertEqual(rejected[0]["corrected_text_at"],
                         "raw/sources/corrected.txt")

    def test_dictionary_clears_the_word_and_only_the_word(self):
        proc = self.run_cli("dict-add", "Zanzibar", "--by",
                            "owner", "--date", "2030-10-20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.list_json()["entries"][0]
        self.assertEqual(entry["counts"],
                         {"dictionary": 1, "open": 1})
        proc = self.run_cli("dict-add", "two words", "--by",
                            "owner")
        self.assertEqual(proc.returncode, 2)


class SidecarTests(unittest.TestCase):
    """The ingest sidecar's extraction block (wiki_convert.py)
    and registration from it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.wc = load_module("wiki_convert",
                              REPO / "scripts" / "wiki_convert.py")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extraction_descriptor_per_format(self):
        pdf = self.wc._extraction_for(Path("x.pdf"))
        self.assertEqual(pdf["method"], "embedded-text")
        self.assertEqual(pdf["confidence"], "unknown")
        self.assertEqual(pdf["state"], "machine-unverified")
        docx = self.wc._extraction_for(Path("x.docx"))
        self.assertEqual(docx["state"], "machine-extracted")
        md = self.wc._extraction_for(Path("x.md"))
        self.assertEqual(md["state"], "not-applicable")

    def test_sidecar_round_trip_and_format_watch_still_reads(self):
        src = self.dir / "note.md"
        src.write_text("# Native\n\nText.\n", encoding="utf-8")
        out = self.dir / "raw" / "sources" / "note.md"
        out.parent.mkdir(parents=True)
        proc = subprocess.run(
            [sys.executable,
             str(REPO / "scripts" / "wiki_convert.py"),
             str(src), "-o", str(out), "--sensitivity",
             "internal"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sidecar = json.loads(
            Path(str(out) + ".ingest.json").read_text())
        self.assertEqual(sidecar["extraction"]["method"],
                         "none")
        self.assertEqual(sidecar["extraction"]["state"],
                         "not-applicable")
        # the Phase-3 reader over the same sidecar, unchanged
        fw = load_module("wiki_format_watch",
                         REPO / "scripts" / "wiki_format_watch.py")
        data = fw.collect(self.dir, None)
        self.assertEqual(len(data["sidecars"]), 1)
        self.assertEqual(data["sidecars"][0]["format"],
                         "Markdown")

    def test_pdf_sidecar_is_machine_unverified(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf not in this interpreter")
        pdf_path = self.dir / "doc.pdf"
        writer = PdfWriter()
        writer.add_blank_page(72, 72)
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        _md, report = self.wc.convert_with_report(pdf_path)
        self.assertEqual(report["extraction"]["method"],
                         "embedded-text")
        self.assertEqual(report["extraction"]["state"],
                         "machine-unverified")
        self.assertEqual(report["extraction"]["confidence"],
                         "unknown")

    def test_enqueue_from_sidecar(self):
        scripts = self.dir / "scripts"
        scripts.mkdir()
        for name in NEEDS:
            shutil.copy(SCRIPTS / name, scripts)
        (self.dir / "raw" / "sources").mkdir(parents=True)
        (self.dir / "raw" / "sources" / "scan.pdf").write_bytes(
            b"%PDF-1.4 fixture")
        (self.dir / "evaluation").mkdir()
        sidecar = {
            "source": str(self.dir / "raw" / "sources"
                          / "scan.pdf"),
            "extraction": {"method": "embedded-text",
                           "tool": "pypdf",
                           "confidence": "unknown",
                           "state": "machine-unverified"},
        }
        sc_path = self.dir / "scan.md.ingest.json"
        sc_path.write_text(json.dumps(sidecar), encoding="utf-8")
        tool = scripts / "wiki_ocr_queue.py"
        proc = subprocess.run(
            [sys.executable, str(tool), "enqueue",
             "--from-sidecar", str(sc_path)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ocr-0001", proc.stdout)
        # a structural extraction has nothing to queue
        sidecar["extraction"] = {
            "method": "ooxml-text", "confidence":
            "not-applicable", "state": "machine-extracted"}
        sc_path.write_text(json.dumps(sidecar), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(tool), "enqueue",
             "--from-sidecar", str(sc_path)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
