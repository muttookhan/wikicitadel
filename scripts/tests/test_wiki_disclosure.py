#!/usr/bin/env python3
"""Pins wiki_disclosure rule. Run: discover -p 'test_wiki_disclosure.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_disclosure as m
def fixture(body):
    d=tempfile.mkdtemp(); r=Path(d); (r/"wiki").mkdir(parents=True); (r/"wiki"/"a.md").write_text(body); return r
class T(unittest.TestCase):
    def test_unlabelled_flagged(self): self.assertEqual(len(m.check(fixture("---\ntitle: A\nautonomous: true\n---\nbody"))),1)
    def test_labelled_ok(self): self.assertEqual(m.check(fixture("---\ntitle: A\nauthor_type: agent\nai_disclosure: true\n---\n> AI disclosure: written autonomously.\nbody")),[])
    def test_human_page_ignored(self): self.assertEqual(m.check(fixture("---\ntitle: A\n---\nbody")),[])
if __name__=="__main__": unittest.main()
