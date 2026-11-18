#!/usr/bin/env python3
"""Tests for scripts/wiki_convert.py — minimal OOXML/HTML fixtures
built with zipfile in a temp dir; the converter must extract text,
headings and tables into Markdown.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_convert", HERE.parents[1] / "wiki_convert.py")
wc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wc)

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
S_NS = ('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

DOCX = f"""<?xml version="1.0"?>
<w:document {W_NS}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly Plan</w:t></w:r></w:p>
<w:p><w:r><w:t>Revenue grew steadily.</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Item</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>Count</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>Widgets</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""

PPTX_SLIDE = f"""<?xml version="1.0"?>
<p:sld {A_NS.replace('xmlns:a', 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a')}>
<p:cSld><p:spTree><p:sp><p:txBody>
<a:p><a:r><a:t>Launch Checklist</a:t></a:r></a:p>
<a:p><a:r><a:t>Book the venue</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"""

XLSX_SHARED = f"""<?xml version="1.0"?>
<sst {S_NS}><si><t>Name</t></si><si><t>Score</t></si><si><t>Ada</t></si></sst>"""
XLSX_WB = f"""<?xml version="1.0"?>
<workbook {S_NS}><sheets><sheet name="Results" sheetId="1" r:id="rId1"/></sheets></workbook>"""
XLSX_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
XLSX_SHEET = f"""<?xml version="1.0"?>
<worksheet {S_NS}><sheetData>
<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
<row><c t="s"><v>2</v></c><c><v>97</v></c></row>
</sheetData></worksheet>"""

HTML = """<html><head><title>T</title><style>body{}</style></head><body>
<h2>Findings</h2><p>We found <strong>three</strong> issues and
<a href="https://example.com/x">a reference</a>.</p>
<ul><li>First</li><li>Second</li></ul><script>evil()</script>
</body></html>"""


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _zip(self, name, members):
        p = self.tmp / name
        with zipfile.ZipFile(p, "w") as zf:
            for arc, data in members.items():
                zf.writestr(arc, data)
        return p

    def test_docx_headings_text_and_table(self):
        p = self._zip("a.docx", {"word/document.xml": DOCX})
        md = wc.convert(p)
        self.assertIn("# Quarterly Plan", md)
        self.assertIn("Revenue grew steadily.", md)
        self.assertIn("| Item | Count |", md)
        self.assertIn("| Widgets | 42 |", md)

    def test_pptx_slides_become_sections(self):
        p = self._zip("a.pptx", {"ppt/slides/slide1.xml": PPTX_SLIDE})
        md = wc.convert(p)
        self.assertIn("## Slide 1", md)
        self.assertIn("Launch Checklist", md)
        self.assertIn("Book the venue", md)

    def test_xlsx_shared_strings_and_table(self):
        p = self._zip("a.xlsx", {
            "xl/sharedStrings.xml": XLSX_SHARED, "xl/workbook.xml": XLSX_WB,
            "xl/_rels/workbook.xml.rels": XLSX_RELS,
            "xl/worksheets/sheet1.xml": XLSX_SHEET})
        md = wc.convert(p)
        self.assertIn("## Results", md)
        self.assertIn("| Name | Score |", md)
        self.assertIn("| Ada | 97 |", md)

    def test_html_to_markdown(self):
        p = self.tmp / "a.html"
        p.write_text(HTML, encoding="utf-8")
        md = wc.convert(p)
        self.assertIn("## Findings", md)
        self.assertIn("**three**", md)
        self.assertIn("[a reference](https://example.com/x)", md)
        self.assertIn("- First", md)
        self.assertNotIn("evil", md)

    def test_markdown_passthrough(self):
        p = self.tmp / "a.md"
        p.write_text("# Keep me\n", encoding="utf-8")
        self.assertEqual(wc.convert(p), "# Keep me\n")

    def test_unsupported_format_refused(self):
        p = self.tmp / "a.xyz"
        p.write_text("?", encoding="utf-8")
        with self.assertRaises(wc.ConvertError):
            wc.convert(p)

    def test_json_becomes_fenced_block(self):
        p = self.tmp / "a.json"
        p.write_text('{"k": 1}', encoding="utf-8")
        self.assertIn('"k": 1', wc.convert(p))


if __name__ == "__main__":
    unittest.main()
