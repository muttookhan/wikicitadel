#!/usr/bin/env python3
"""Tests for wiki_block_embeds. Pins embed resolution by title and block id, duplicate detection, missing embed."""
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("be",ROOT/"scripts/wiki_block_embeds.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree():
    r=Path(tempfile.mkdtemp())
    for n,t in {"src.md":"---\ntitle: S\n---\n## Details {#det}\nThe details text.\n## Other\nother\n","main.md":"---\ntitle: M\n---\nBefore\n![[src#Details]]\nAfter\n"}.items():
        p=r/"wiki"/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(t)
    return r
class T(unittest.TestCase):
    def test_embed_by_title(self):
        pages,_=m.collect(tree()); out,miss=m.render("![[src#Details]]",pages); self.assertIn("details text",out); self.assertEqual(miss,[])
    def test_embed_by_block_id(self):
        pages,_=m.collect(tree()); out,miss=m.render("![[src#det]]",pages); self.assertIn("details text",out)
    def test_missing(self):
        pages,_=m.collect(tree()); out,miss=m.render("![[src#Nope]]",pages); self.assertEqual(len(miss),1)
    def test_duplicate_block_id(self):
        r=tree(); (r/"wiki/dup.md").write_text("---\ntitle: D\n---\n## X {#det}\ny\n"); _,probs=m.collect(r); self.assertTrue(any(p["problem"]=="duplicate block id" for p in probs))
if __name__=="__main__": unittest.main()
