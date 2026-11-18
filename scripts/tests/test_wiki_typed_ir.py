#!/usr/bin/env python3
"""Tests for wiki_typed_ir. Pins block typing and freshness."""
import importlib.util, tempfile, unittest, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("ir",ROOT/"scripts/wiki_typed_ir.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree(txt="---\ntitle: A\n---\n# Head\npara text\n- item\n[[b]]\n"):
    r=Path(tempfile.mkdtemp()); p=r/"wiki/a.md"; p.parent.mkdir(parents=True); p.write_text(txt); return r
class T(unittest.TestCase):
    def test_block_types(self):
        types=[b["type"] for b in m.build(tree())["pages"][0]["blocks"]]; self.assertIn("heading",types); self.assertIn("list_item",types); self.assertIn("wikilink",types)
    def test_fresh_after_build(self):
        r=tree(); c=r/"ir.json"; c.write_text(json.dumps(m.build(r))); self.assertEqual(m.stale(r,c),[])
    def test_stale_after_edit(self):
        r=tree(); c=r/"ir.json"; c.write_text(json.dumps(m.build(r))); (r/"wiki/a.md").write_text("---\ntitle: A\n---\nchanged\n"); self.assertEqual(m.stale(r,c),["wiki/a.md"])
    def test_missing_cache_all_stale(self): self.assertTrue(m.stale(tree(),"/nonexistent/x.json"))
if __name__=="__main__": unittest.main()
