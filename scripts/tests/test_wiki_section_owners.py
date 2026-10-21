#!/usr/bin/env python3
"""Tests for wiki_section_owners. Pins unowned, multiply-owned, clean cases."""
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("so",ROOT/"scripts/wiki_section_owners.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree(txt):
    r=Path(tempfile.mkdtemp()); p=r/"wiki/a.md"; p.parent.mkdir(parents=True); p.write_text(txt); return r
class T(unittest.TestCase):
    def test_unowned(self):
        d=m.check(tree("---\ntitle: A\nsection_owners:\n  Intro: owner-a\n---\n## Intro\nx\n## Other\ny\n")); self.assertEqual(d["problems"][0]["problem"],"unowned")
    def test_clean(self):
        d=m.check(tree("---\ntitle: A\nsection_owners:\n  Intro: owner-a\n---\n## Intro\nx\n")); self.assertEqual(d["problems"],[])
    def test_multiply_owned(self):
        d=m.check(tree("---\ntitle: A\nsection_owners:\n  Intro: owner-a\n---\n## Intro\n<!-- section-owner: owner-b -->\nx\n")); self.assertEqual(d["problems"][0]["problem"],"multiply-owned")
    def test_inline_only_clean(self):
        d=m.check(tree("---\ntitle: A\n---\n## Intro\n<!-- section-owner: owner-a -->\nx\n")); self.assertEqual(d["problems"],[])
    def test_no_declaration_no_problems(self):
        d=m.check(tree("---\ntitle: A\n---\n## Intro\nx\n")); self.assertEqual(d["problems"],[])
if __name__=="__main__": unittest.main()
