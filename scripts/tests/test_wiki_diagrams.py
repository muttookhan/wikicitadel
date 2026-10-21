#!/usr/bin/env python3
"""Pins wiki_diagrams checker. Run: python3 -m unittest discover -s scripts/tests -p 'test_wiki_diagrams.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_diagrams as m
def tree(spec):
    d=tempfile.mkdtemp(); r=Path(d)
    for p in spec: (r/p).parent.mkdir(parents=True,exist_ok=True); (r/p).write_text("x")
    return r
class T(unittest.TestCase):
    def test_good_pair_passes(self): self.assertEqual(m.check(tree(["diagrams/flow.excalidraw","diagrams/flow.svg"])),[])
    def test_outside_flagged(self): self.assertTrue(any(f["kind"]=="outside-diagrams" for f in m.check(tree(["wiki/x.excalidraw"]))))
    def test_unpaired_flagged(self):
        kinds={f["kind"] for f in m.check(tree(["diagrams/lonely.excalidraw","diagrams/orphan.svg"]))}
        self.assertIn("source-without-export",kinds); self.assertIn("export-without-source",kinds)
    def test_bad_stem(self): self.assertTrue(any(f["kind"]=="bad-stem" for f in m.check(tree(["diagrams/Bad_Stem.excalidraw","diagrams/Bad_Stem.svg"]))))
if __name__=="__main__": unittest.main()
