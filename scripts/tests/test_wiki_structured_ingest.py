#!/usr/bin/env python3
"""Docling-pattern structured ingest (Marathon Round 3, lane
TB7, row 5).

Pins on fixture documents: a markdown fixture yields the typed
block stream (heading with level, paragraph, table with headers
+ rows, ordered and unordered lists, fenced code with language,
blockquote) in source order; an HTML fixture run through the
full CLI gains both the markdown and the blocks JSON beside it;
counts match the blocks. The converter itself is untouched by
this row — the module post-processes its output.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_structured_ingest",
    ROOT / "scripts" / "wiki_structured_ingest.py")
SI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SI)

MD = """# Title One

Intro paragraph here.

## Section

| Name | Kind |
| --- | --- |
| alpha | entity |
| beta | concept |

- first item
- second item

1. step one
2. step two

```python
print("hi")
```

> a quoted line
> continues here

Closing paragraph.
"""


class ParseBlocksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = SI.structured_document("fixture.md", MD)
        cls.blocks = cls.doc["blocks"]

    def types(self):
        return [b["type"] for b in self.blocks]

    def test_block_stream_order_and_types(self):
        self.assertEqual(self.types(),
                         ["heading", "paragraph", "heading", "table",
                          "list", "list", "code", "blockquote",
                          "paragraph"])
        self.assertEqual(self.doc["kind"], "structured-document")
        self.assertEqual(sum(self.doc["counts"].values()),
                         len(self.blocks))

    def test_typed_payloads(self):
        h = self.blocks[0]
        self.assertEqual((h["level"], h["text"]), (1, "Title One"))
        table = self.blocks[3]
        self.assertEqual(table["headers"], ["Name", "Kind"])
        self.assertEqual(table["rows"],
                         [["alpha", "entity"], ["beta", "concept"]])
        ul, ol = self.blocks[4], self.blocks[5]
        self.assertFalse(ul["ordered"])
        self.assertEqual(ul["items"], ["first item", "second item"])
        self.assertTrue(ol["ordered"])
        self.assertEqual(ol["items"], ["step one", "step two"])
        code = self.blocks[6]
        self.assertEqual(code["language"], "python")
        self.assertEqual(code["text"], 'print("hi")')
        self.assertIn("quoted line", self.blocks[7]["text"])


class CliTests(unittest.TestCase):
    def test_html_fixture_gains_blocks_json(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "doc.html"
            src.write_text(
                "<html><body><h1>Heading</h1><p>Body text.</p>"
                "</body></html>", encoding="utf-8")
            out = Path(td) / "doc.md"
            r = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "wiki_structured_ingest.py"),
                 str(src), "-o", str(out)],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.is_file())
            doc = json.loads(
                Path(str(out) + ".blocks.json").read_text())
            self.assertEqual(doc["kind"], "structured-document")
            types = [b["type"] for b in doc["blocks"]]
            self.assertIn("heading", types)
            self.assertIn("paragraph", types)

    def test_missing_file_is_exit_2(self):
        r = subprocess.run(
            [sys.executable,
             str(ROOT / "scripts" / "wiki_structured_ingest.py"),
             "/nonexistent/file.md"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
