#!/usr/bin/env python3
"""Tests for wiki_current_understanding. Pins entity-only generation and extractive claims."""
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("cu",ROOT/"scripts/wiki_current_understanding.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def tree():
    r=Path(tempfile.mkdtemp())
    for n,t in {"entities/e.md":"---\ntitle: Ent\ntype: entity\nstatus: verified\nconfidence: medium\nupdated: 2026-01-01\n---\n- Claim one\n- Claim two\n","concepts/c.md":"---\ntitle: C\ntype: concept\n---\n- not entity\n"}.items():
        p=r/"wiki"/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(t)
    return r
class T(unittest.TestCase):
    def test_only_entities(self):
        docs=m.generate(tree(),Path(tempfile.mkdtemp())); self.assertEqual(len(docs),1); self.assertEqual(docs[0]["claims"],["Claim one","Claim two"])
    def test_verification_state_carried(self):
        docs=m.generate(tree(),Path(tempfile.mkdtemp())); self.assertEqual(docs[0]["status"],"verified")
    def test_file_written(self):
        out=Path(tempfile.mkdtemp()); m.generate(tree(),out); self.assertIn("Claim one",(out/"e.md").read_text())
if __name__=="__main__": unittest.main()
