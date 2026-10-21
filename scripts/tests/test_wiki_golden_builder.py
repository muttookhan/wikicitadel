#!/usr/bin/env python3
"""Pins wiki_golden_builder: verification + golden set byte-untouched + no overwrite.
Run: discover -p 'test_wiki_golden_builder.py'"""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_golden_builder as m
class T(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); self.r=Path(self.d); (self.r/"src").mkdir()
        (self.r/"src"/"a.md").write_text("# A\n\nThe verifiable history chain records every version of a document in order. Another sufficiently long sentence about archival practice and provenance follows here.")
        self.golden=self.r/"golden-questions.jsonl"; self.golden.write_text('{"q":"keep me"}\n'); self.h=hashlib.sha256(self.golden.read_bytes()).hexdigest()
    def test_build_and_golden_untouched(self):
        out=self.r/"candidates.jsonl"; rc=m.main(["--source-dir",str(self.r/"src"),"--out",str(out)])
        self.assertEqual(rc,0); rows=[json.loads(l) for l in out.read_text().splitlines()]
        self.assertTrue(any(r["answerable"] for r in rows)); self.assertTrue(any(not r["answerable"] for r in rows))
        self.assertTrue(all(r["verified"] for r in rows))
        self.assertEqual(hashlib.sha256(self.golden.read_bytes()).hexdigest(),self.h)
    def test_refuses_golden_and_existing(self):
        self.assertEqual(m.main(["--source-dir",str(self.r/"src"),"--out",str(self.golden)]),4)
        self.assertEqual(hashlib.sha256(self.golden.read_bytes()).hexdigest(),self.h)
if __name__=="__main__": unittest.main()
