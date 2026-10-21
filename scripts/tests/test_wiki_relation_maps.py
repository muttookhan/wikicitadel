#!/usr/bin/env python3
"""Tests for wiki_relation_maps. Pins: typed edges, relation map grouping, hoisting threshold. Run: python3 -m unittest discover -s scripts/tests -p test_wiki_relation_maps.py"""
import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("rm",ROOT/"scripts/wiki_relation_maps.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree(pages):
    d=tempfile.mkdtemp(); r=Path(d)
    for name,txt in pages.items():
        p=r/"wiki"/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(txt)
    return r
FM="---\ntitle: T\ntype: concept\n---\n"
class T(unittest.TestCase):
    def test_wikilink_edge(self):
        r=tree({"a.md":FM+"See [[b]]","b.md":FM+"hi"})
        d=m.build(r); self.assertTrue(any(e["target"]=="b" for e in d["edges"]))
    def test_typed_frontmatter_edge(self):
        r=tree({"a.md":"---\ntitle: T\nlinks:\n  - grounds: b\n---\nbody","b.md":FM+"x"})
        d=m.build(r); self.assertIn("grounds",d["edge_types"])
    def test_hoisting_threshold(self):
        pages={"hub.md":FM+"[[a]] [[b]] [[c]]","a.md":FM+"","b.md":FM+"","c.md":FM+"","solo.md":FM+"[[a]]"}
        d=m.build(tree(pages)); self.assertEqual([h["page"] for h in d["hoisting"]],["wiki/hub.md"])
    def test_empty(self):
        d=m.build(tree({})); self.assertEqual(d["edges"],[])
    def test_deterministic(self):
        r=tree({"a.md":FM+"[[b]]","b.md":FM+""}); self.assertEqual(m.build(r),m.build(r))
if __name__=="__main__": unittest.main()
