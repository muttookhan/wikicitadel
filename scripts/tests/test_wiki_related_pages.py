#!/usr/bin/env python3
"""Tests for wiki_related_pages. Pins tag/link/term scoring and ordering."""
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("rp",ROOT/"scripts/wiki_related_pages.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree():
    r=Path(tempfile.mkdtemp())
    for n,t in {"a.md":"---\ntitle: A\ntags: [x, y]\n---\nalpha beta gamma [[b]]\n","b.md":"---\ntitle: B\ntags: [x]\n---\nalpha beta\n","c.md":"---\ntitle: C\ntags: [z]\n---\nunrelated words here\n"}.items():
        p=r/"wiki"/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(t)
    return r
class T(unittest.TestCase):
    def test_b_related_to_a_first(self):
        d=m.compute(tree()); rel=d["related"]["wiki/a.md"]; self.assertEqual(rel[0]["page"],"wiki/b.md")
    def test_unrelated_low_or_absent(self):
        d=m.compute(tree()); pages=[x["page"] for x in d["related"]["wiki/a.md"]]; self.assertTrue("wiki/c.md" not in pages or d["related"]["wiki/a.md"][-1]["page"]=="wiki/c.md")
    def test_why_present(self):
        d=m.compute(tree()); self.assertTrue(any("tags" in w for w in d["related"]["wiki/a.md"][0]["why"]))
if __name__=="__main__": unittest.main()
