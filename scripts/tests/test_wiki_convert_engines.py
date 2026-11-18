#!/usr/bin/env python3
"""W4 document-engine trials: the engine seam behind wiki_convert.

The registry / probe / complexity-scored auto-selection /
invented-content check live in scripts/wiki_convert_engines.py;
the seam (explicit --engine selection, named doors, the sidecar
"engine" block) lives in scripts/wiki_convert.py.

No heavyweight engine is installed in this environment and no
test may install one: unavailable engines are exercised as DOORS
with their probe blockers named, and the engine path itself is
exercised end-to-end with a STUB engine registered in-process —
which proves selection, the injection gate, and the sidecar
shape without pretending a real engine ran.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


eng = _load("wiki_convert_engines")
wc = _load("wiki_convert")

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
DOCX = f"""<?xml version="1.0"?>
<w:document {W_NS}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly Plan</w:t></w:r></w:p>
<w:p><w:r><w:t>Revenue grew steadily.</w:t></w:r></w:p>
</w:body></w:document>"""


def make_docx(tmp, name="plain.docx", tables=0, images=0,
              pad_bytes=0):
    body = DOCX
    if tables:
        tbl = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Item</w:t></w:r>"
               "</w:p></w:tc></w:tr></w:tbl>")
        body = body.replace("</w:body>", tbl * tables + "</w:body>")
    p = tmp / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml", body)
        for i in range(images):
            zf.writestr(f"word/media/image{i}.png", b"\x89PNG")
        if pad_bytes:
            zf.writestr("word/embeddings/pad.bin",
                        b"\0" * pad_bytes)
    return p


def rich_docx(tmp, name="rich.docx"):
    """Tables (capped +0.30) + images (capped +0.20) + size
    (+0.15 over 1MB) = complexity 0.65, band 'complex'."""
    return make_docx(tmp, name, tables=3, images=5,
                     pad_bytes=1_100_000)


def register_stub(testcase, name="stubengine", tier=2,
                  formats=(".docx", ".pdf"), md="# Stub Title\n\n"
                  "Stub body text with several distinct words "
                  "for the quality scorer to chew on.\n"):
    """Register a fake engine whose probe passes (a module object
    in sys.modules) and whose adapter returns canned markdown."""
    fake = types.ModuleType(name)
    fake.__version__ = "9.9-test"
    sys.modules[name] = fake
    testcase.addCleanup(sys.modules.pop, name, None)
    spec = {"name": name, "label": f"Stub ({name})",
            "modules": [name], "formats": set(formats),
            "tier": tier, "licence": "test-only",
            "licence_route": "interface-only",
            "deterministic": "yes (canned)",
            "adapter": lambda path: md,
            "notes": "test stub"}
    eng.ENGINES[name] = spec
    testcase.addCleanup(eng.ENGINES.pop, name, None)
    return spec


class RegistryTests(unittest.TestCase):
    def test_four_engines_registered_with_licence_routes(self):
        self.assertEqual(set(eng.ENGINES),
                         {"docling", "markitdown", "unstructured",
                          "marker"})
        self.assertEqual(eng.ENGINES["docling"]["licence"], "MIT")
        self.assertEqual(eng.ENGINES["markitdown"]["licence"],
                         "MIT")
        self.assertEqual(eng.ENGINES["unstructured"]["licence"],
                         "Apache-2.0")
        for name in ("docling", "markitdown", "unstructured"):
            self.assertEqual(eng.ENGINES[name]["licence_route"],
                             "adapt-with-credit")
        # Marker's licence is in flux on the record (GPL-3.0
        # history vs Apache-2.0 README + restricted weights):
        # interface only, never adapted.
        self.assertEqual(eng.ENGINES["marker"]["licence_route"],
                         "interface-only")

    def test_probe_reports_unavailable_engines_honestly(self):
        for name in eng.ENGINES:
            rec = eng.probe_engine(name)
            if rec["probe"]["available"]:
                self.skipTest(f"{name} is installed here; the "
                              f"door assertions do not apply")
            self.assertIn("ModuleNotFoundError",
                          rec["probe"]["blocker"])


class ComplexityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.tmp, ignore_errors=True))

    def test_native_text_is_simple(self):
        p = self.tmp / "note.md"
        p.write_text("# Title\n\nSome text.\n")
        c = eng.document_complexity(p)
        self.assertEqual(c["band"], "simple")
        self.assertEqual(c["signals"]["family"], "native text")

    def test_tables_and_images_raise_docx_complexity(self):
        plain = eng.document_complexity(make_docx(self.tmp, "a.docx"))
        rich = eng.document_complexity(rich_docx(self.tmp, "b.docx"))
        self.assertEqual(plain["signals"]["tables"], 0)
        self.assertEqual(rich["signals"]["tables"], 3)
        self.assertEqual(rich["signals"]["images"], 5)
        self.assertGreater(rich["score"], plain["score"])
        self.assertEqual(rich["band"], "complex")

    def test_unknown_pdf_signals_are_stated_not_guessed(self):
        p = self.tmp / "broken.pdf"
        p.write_bytes(b"%PDF-1.4 not really a pdf")
        c = eng.document_complexity(p)
        self.assertIn("pdf_probe", c["signals"])
        self.assertIn("unknown, not guessed",
                      c["signals"]["pdf_probe"])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            self.tmp, ignore_errors=True))

    def test_default_path_is_byte_identical_and_enginesilent(self):
        p = make_docx(self.tmp)
        md_default, rep_default = wc.convert_with_report(p)
        md_none, rep_none = wc.convert_with_report(p, engine=None)
        self.assertEqual(md_default, md_none)
        self.assertNotIn("engine", rep_default)
        self.assertNotIn("engine", rep_none)

    def test_unknown_engine_is_a_plain_error(self):
        p = make_docx(self.tmp)
        with self.assertRaises(wc.ConvertError):
            wc.convert_with_report(p, engine="nosuchengine")

    def test_unavailable_engine_is_a_named_door(self):
        if eng.probe_engine("docling")["probe"]["available"]:
            self.skipTest("docling installed here")
        p = make_docx(self.tmp)
        with self.assertRaises(wc.ConversionDoorError) as ctx:
            wc.convert_with_report(p, engine="docling")
        exc = ctx.exception
        self.assertEqual(exc.door["name"], "engine-unavailable")
        self.assertEqual(exc.door["engine"], "docling")
        self.assertIn("ModuleNotFoundError", exc.door["reason"])
        self.assertIsNone(exc.report["engine"]["ran"])
        # the door sidecar still carries the standard blocks
        for key in ("conversion_loss", "format_evaluation",
                    "sanitiser", "converter"):
            self.assertIn(key, exc.report)

    def test_engine_format_unsupported_is_a_named_door(self):
        register_stub(self, formats=(".pdf",))
        p = make_docx(self.tmp)
        with self.assertRaises(wc.ConversionDoorError) as ctx:
            wc.convert_with_report(p, engine="stubengine")
        self.assertEqual(ctx.exception.door["name"],
                         "engine-format-unsupported")

    def test_stub_engine_runs_behind_the_injection_gate(self):
        register_stub(self)
        p = make_docx(self.tmp)
        md, report = wc.convert_with_report(p, engine="stubengine")
        self.assertIn("Stub Title", md)
        block = report["engine"]
        self.assertEqual(block["ran"], "stubengine")
        self.assertEqual(block["mode"], "explicit")
        self.assertEqual(block["identity"]["version"], "9.9-test")
        self.assertEqual(report["extraction"]["state"],
                         "machine-unverified")
        self.assertEqual(report["extraction"]["tool"],
                         "stubengine")
        self.assertTrue(any("stubengine" in note
                            for note in report["conversion_loss"]))
        self.assertIn("parse_quality", report)
        self.assertIn("sanitiser", report)

    def test_engine_output_is_sanitised(self):
        # a zero-width space smuggled in the engine's output must
        # be stripped by the same gate the built-in routes pass
        hostile = "# Title\n\nClean words here\u200b plus more text.\n"
        register_stub(self, md=hostile)
        p = make_docx(self.tmp)
        md, report = wc.convert_with_report(p, engine="stubengine")
        self.assertNotIn("\u200b", md)
        self.assertTrue(report["sanitiser"]["findings"])

    def test_quality_gate_applies_on_the_engine_path(self):
        register_stub(self, md="same same same same same same\n")
        p = make_docx(self.tmp)
        with self.assertRaises(wc.ParseQualityError):
            wc.convert_with_report(p, engine="stubengine",
                                   quality_threshold=0.99)

    def test_auto_falls_back_to_builtin_with_the_gap_recorded(self):
        p = self.tmp / "note.txt"
        p.write_text("plain simple text, nothing complex\n")
        md, report = wc.convert_with_report(p, engine="auto")
        self.assertIn("plain simple text", md)
        block = report["engine"]
        self.assertEqual(block["ran"], "builtin")
        self.assertEqual(block["mode"], "auto")
        self.assertIsNotNone(block["recommendation"])
        self.assertIn("complexity", block)

    def test_auto_routes_complex_docx_to_available_engine(self):
        register_stub(self)
        p = rich_docx(self.tmp)
        _md, report = wc.convert_with_report(p, engine="auto")
        self.assertEqual(report["engine"]["ran"], "stubengine")
        self.assertGreaterEqual(
            report["engine"]["complexity"]["score"], 0.55)


class InventedContentTests(unittest.TestCase):
    def test_clean_conversion_invents_nothing(self):
        r = eng.invented_content_check(
            "the quick brown fox jumps",
            "the quick brown fox jumps\n")
        self.assertEqual(r["invented_tokens"], 0)
        self.assertEqual(r["invented_ratio"], 0.0)

    def test_added_tokens_are_counted_and_named(self):
        r = eng.invented_content_check(
            "the quick brown fox",
            "## Page 1\n\nthe quick brown fox zebra\n")
        self.assertIn("zebra", r["invented_sample"])
        self.assertGreater(r["invented_ratio"], 0.0)


class CliTests(unittest.TestCase):
    def test_engines_listing_is_json_with_probes(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "wiki_convert.py"),
             "--engines"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(set(data), {"docling", "markitdown",
                                     "unstructured", "marker"})
        for rec in data.values():
            self.assertIn("probe", rec)
            self.assertIn("licence_route", rec)


if __name__ == "__main__":
    unittest.main()
