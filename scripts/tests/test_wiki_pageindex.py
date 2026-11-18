#!/usr/bin/env python3
"""Phase-2 harvest item 2: PageIndex for long documents
(pattern: VectifyAI/OpenKB, Apache-2.0).

Proves, on generated fixture PDFs (stdlib writer, uncompressed
streams so the built-in extractor path is what runs):
- a >= 20-page PDF gets a hierarchical section tree artefact with
  extractive (verbatim) summaries;
- a short PDF is skipped below the threshold;
- scripts/wiki_search.py traverses the tree and lands on the
  right section with its page range.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pi = _load("wiki_pageindex")
ws = _load("wiki_search")

BODY = ("The {topic} programme is described in this section with enough "
        "detail for a reader to follow the whole argument carefully. "
        "Evidence for the {topic} approach comes from classroom practice "
        "recorded over several terms in the school register. "
        "Teachers review the {topic} material each Friday and note what "
        "needs to change before the next week begins.")


def make_pdf(path: Path, pages_lines: list[list[str]]):
    """A minimal valid PDF: one uncompressed content stream per
    page, one Tj per line. Enough for the stdlib extractor."""
    n = len(pages_lines)
    bodies = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
              3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids, page_objs = [], []
    next_id = 4
    for _ in range(n):
        kids.append(next_id)
        page_objs.append((next_id, next_id + 1))
        next_id += 2
    bodies[2] = ("<< /Type /Pages /Kids ["
                 + " ".join(f"{k} 0 R" for k in kids)
                 + f"] /Count {n} >>").encode()
    for (page_id, content_id), lines in zip(page_objs, pages_lines):
        bodies[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>").encode()
        ops = ["BT", "/F1 14 Tf", "1 0 0 1 72 720 Tm"]
        for line in lines:
            esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({esc}) Tj")
            ops.append("0 -18 Td")
        ops.append("ET")
        raw = "\n".join(ops).encode("latin-1")
        bodies[content_id] = (b"<< /Length " + str(len(raw)).encode()
                              + b" >>\nstream\n" + raw + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(bodies):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + bodies[num] + b"\nendobj\n"
    xref = len(out)
    top = max(bodies)
    out += f"xref\n0 {top + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, top + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {top + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


def chapter_pages(topic, heading, count, start_sentence=None):
    pages = []
    for i in range(count):
        lines = []
        if i == 0:
            lines.append(heading)
        lines.append(BODY.format(topic=topic))
        if start_sentence:
            lines.append(start_sentence)
        pages.append(lines)
    return pages


class TestPageIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "pageindex"
        pages = []
        pages += chapter_pages("irrigation", "Chapter 1 Irrigation Basics", 6)
        pages += chapter_pages("timetable", "Chapter 2 The Weekly Timetable", 6)
        pages += chapter_pages("rubric", "Chapter 3 Assessment Rubrics", 6)
        pages += chapter_pages("garden", "Chapter 4 The School Garden", 6)
        self.doc = self.dir / "longbook.pdf"
        make_pdf(self.doc, pages)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extraction_page_count(self):
        pages, outline, extractor = pi.extract(self.doc)
        self.assertEqual(len(pages), 24)
        self.assertIn("Chapter 1 Irrigation Basics", pages[0])

    def test_build_tree_and_extractive_summaries(self):
        res = pi.build_index(self.doc, min_pages=20, out_dir=self.out)
        self.assertTrue(res["built"], res)
        self.assertEqual(res["pages"], 24)
        import json
        art = json.loads((self.out / "longbook.json").read_text(encoding="utf-8"))
        titles = [n["title"] for n in art["tree"]]
        self.assertIn("Chapter 3 Assessment Rubrics", titles)
        ch3 = next(n for n in art["tree"] if n["title"].startswith("Chapter 3"))
        self.assertEqual(ch3["pages"], [13, 18])
        self.assertTrue(ch3["summary"])
        # Extractive means verbatim: every summary sentence must
        # appear in the extracted source text.
        pages, _o, _e = pi.extract(self.doc)
        flat = " ".join("\n".join(pages).split())
        for sent in ch3["summary"].split(". "):
            sent = sent.strip().rstrip(".")
            if sent:
                self.assertIn(sent, flat)
        # The rendered view exists too.
        self.assertTrue((self.out / "longbook.md").exists())

    def test_short_pdf_skipped_below_threshold(self):
        small = self.dir / "small.pdf"
        make_pdf(small, chapter_pages("irrigation", "Chapter 1 Short", 3))
        res = pi.build_index(small, min_pages=20, out_dir=self.out)
        self.assertFalse(res["built"])
        self.assertIn("threshold", res["reason"])

    def test_search_traverses_the_tree(self):
        pi.build_index(self.doc, min_pages=20, out_dir=self.out)
        hits = ws.pageindex_matches(["rubric"], pageindex_dir=self.out)
        self.assertTrue(hits)
        top = hits[0]
        self.assertEqual(top["pages"], [13, 18])
        self.assertIn("Assessment Rubrics", " > ".join(top["trail"]))


if __name__ == "__main__":
    unittest.main()
