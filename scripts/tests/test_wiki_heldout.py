#!/usr/bin/env python3
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name, rel):
    spec=importlib.util.spec_from_file_location(name, ROOT/rel); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
"""Pins held-out machinery: manifest hashes an external fixture set, tamper blocks the run, report carries aggregates only.
Run: python3 -m unittest discover -s scripts/tests"""
m=load("ho","scripts/wiki_heldout.py")
class T(unittest.TestCase):
    def test_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); tree=td/"tree"; (tree/"evaluation").mkdir(parents=True)
            ext=td/"external"/"heldout.jsonl"; ext.parent.mkdir()
            ext.write_text(json.dumps({"id":"H1","question":"secret fixture question","expected":"bell cast 1881","answer":"the bell was cast in 1881"})+"\n")
            rep=m.write_manifest(tree, ext); self.assertEqual(rep["status"],"written")
            r=m.run(tree); self.assertEqual(r["status"],"scored"); self.assertEqual(r["passed"],1)
            self.assertNotIn("secret fixture question", json.dumps(r))
            ext.write_text(ext.read_text()+" ")
            self.assertEqual(m.run(tree)["status"],"refused")
    def test_no_manifest_refused(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/"evaluation").mkdir(); self.assertEqual(m.run(td)["status"],"refused")
if __name__=="__main__": unittest.main()
