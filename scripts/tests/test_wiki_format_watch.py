"""Tests for item 28 (format-risk watch): signature-based
identification in wiki_convert.identify_format (never the
extension alone, PUID never invented), the ingest sidecar
carrying format + puid, and wiki_format_watch's report over a
fixture raw/ tree.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve()


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, HERE.parents[1] / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wc = _load("wiki_convert")
fw = _load("wiki_format_watch")

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
DOCX_XML = (f'<?xml version="1.0"?><w:document {W_NS}><w:body>'
            '<w:p><w:r><w:t>Hi</w:t></w:r></w:p></w:body></w:document>')


class IdentifyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data, binary=False):
        p = self.dir / name
        if binary:
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")
        return p

    def test_pdf_by_signature(self):
        p = self._write("a.pdf", b"%PDF-1.7\nbody", binary=True)
        ident = wc.identify_format(p)
        self.assertEqual(ident["format"], "PDF")
        self.assertEqual(ident["basis"], "signature")
        self.assertFalse(ident["extension_mismatch"])

    def test_docx_by_container_signature(self):
        p = self.dir / "a.docx"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("word/document.xml", DOCX_XML)
        ident = wc.identify_format(p)
        self.assertEqual(ident["format"], "DOCX")
        self.assertEqual(ident["basis"], "signature")

    def test_plain_zip_by_signature(self):
        p = self.dir / "a.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("inner.txt", "hello")
        self.assertEqual(wc.identify_format(p)["format"],
                         "ZIP Archive")

    def test_extension_mismatch_flagged(self):
        # DOCX bytes wearing a .pdf name: the signature wins and
        # the lie is flagged (find 13's EXTENSION_MISMATCH).
        p = self.dir / "lying.pdf"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("word/document.xml", DOCX_XML)
        ident = wc.identify_format(p)
        self.assertEqual(ident["format"], "DOCX")
        self.assertTrue(ident["extension_mismatch"])

    def test_json_and_html_by_text(self):
        p = self._write("a.json", '{"k": 1}')
        self.assertEqual(wc.identify_format(p)["format"], "JSON")
        p = self._write("a.html",
                        "<!DOCTYPE html>\n<html><body>x</body></html>")
        self.assertEqual(wc.identify_format(p)["format"], "HTML")

    def test_markdown_by_extension_and_no_invented_puid(self):
        p = self._write("a.md", "# Title\n\nplain prose, no sig\n")
        ident = wc.identify_format(p)
        self.assertEqual(ident["format"], "Markdown")
        self.assertEqual(ident["basis"], "extension")
        # The wave-6 find states no per-format PUID values and
        # none exist in the local record: the puid must be the
        # honest placeholder, never a number from memory.
        self.assertEqual(ident["puid"], "unverified")

    def test_sidecar_carries_format_and_puid(self):
        p = self._write("note.md", "# Note\n\nbody text\n")
        out = self.dir / "note-out.md"
        rc = wc.main([str(p), "-o", str(out)])
        self.assertEqual(rc, 0)
        sidecar = Path(str(out) + ".ingest.json")
        rec = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(rec["format"], "Markdown")
        self.assertEqual(rec["puid"], "unverified")
        self.assertEqual(rec["format_basis"], "extension")
        self.assertFalse(rec["extension_mismatch"])
        # converter identity (item 8) still recorded alongside
        self.assertIn("converter", rec)
        self.assertIn("sanitiser", rec)


class WatchReportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        raw = self.root / "raw" / "sources"
        raw.mkdir(parents=True)
        (raw / "a.md").write_text("# a\n", encoding="utf-8")
        (raw / "b.md").write_text("# b\n", encoding="utf-8")
        (raw / "report.pdf").write_bytes(b"%PDF-1.7\nx")
        (raw / "cap.warc").write_bytes(b"WARC/1.0\r\n\r\n")
        (raw / "note.md.ingest.json").write_text(json.dumps({
            "format": "Markdown", "puid": "unverified",
            "format_basis": "extension", "extension_mismatch": False,
            "converter": {"format": "md"}}), encoding="utf-8")
        self.watch = {"watch": [
            {"format": "PDF", "extensions": [".pdf"],
             "risk": "r", "migration": "m", "risk_class": "watch"},
            {"format": "WARC", "extensions": [".warc"],
             "risk": "r", "migration": "m", "risk_class": "watch"}]}

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_classifies_by_risk(self):
        data = fw.collect(self.root, self.watch)
        census = {r["extension"]: r for r in data["census"]}
        self.assertEqual(census[".md"]["count"], 2)
        self.assertEqual(census[".md"]["risk_class"], "standard")
        self.assertEqual(census[".pdf"]["risk_class"], "watch")
        self.assertEqual(census[".warc"]["risk_class"], "watch")
        self.assertEqual(data["census_files"], 4)  # sidecar excluded
        self.assertEqual(len(data["sidecars"]), 1)
        self.assertEqual(data["sidecar_formats"][0]["format"],
                         "Markdown")
        text = fw.render(data)
        self.assertIn("Coverage honesty", text)
        self.assertIn("PDF", text)

if __name__ == "__main__":
    unittest.main()
