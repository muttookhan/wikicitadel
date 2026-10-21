#!/usr/bin/env python3
"""Pins wiki_gen_templates lister incl. shipped examples. Run: discover -p 'test_wiki_gen_templates.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_gen_templates as m
class T(unittest.TestCase):
    def test_shipped_templates_valid(self):
        root=Path(__file__).resolve().parent.parent.parent
        out,err=m.list_templates(root); self.assertEqual(err,[]); self.assertGreaterEqual(len(out),3)
    def test_missing_field_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d); (r/"templates"/"generation").mkdir(parents=True)
            (r/"templates"/"generation"/"bad.md").write_text("---\nname: Bad\n---\nbody")
            _,err=m.list_templates(r); self.assertEqual(len(err),1)
if __name__=="__main__": unittest.main()
