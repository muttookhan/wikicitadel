#!/usr/bin/env python3
"""Pins wiki_naming_lock checker. Run: discover -p 'test_wiki_naming_lock.py'"""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_naming_lock as m
def fixture(stems, locked, ledger=None):
    d=tempfile.mkdtemp(); r=Path(d); (r/"wiki"/"rules").mkdir(parents=True); (r/"wiki"/"concepts").mkdir(parents=True)
    for s in stems: (r/"wiki"/"concepts"/f"{s}.md").write_text("x")
    (r/"wiki"/"rules"/"naming-lock.json").write_text(json.dumps({"locked":[{"stem":s} for s in locked]}))
    if ledger is not None: (r/"wiki"/"rules"/"naming-lock-ledger.jsonl").write_text(ledger)
    return r
class T(unittest.TestCase):
    def test_present_ok(self): self.assertEqual(m.check(fixture(["alpha"],["alpha"])),[])
    def test_missing_flagged(self): self.assertEqual(m.check(fixture([],["alpha"]))[0]["kind"],"locked-stem-missing")
    def test_ledger_rename_excused(self): self.assertEqual(m.check(fixture(["beta"],["alpha"],'{ "old_stem": "alpha", "new_stem": "beta" }\n')),[])
if __name__=="__main__": unittest.main()
