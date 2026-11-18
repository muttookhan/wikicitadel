#!/usr/bin/env python3
"""Pins wiki_packing_check: the Lost-in-the-Middle position check
(Marathon R4 lane D, item 1).

A pack produced by evidence_packing.pack_evidence holds; a pack
with the strongest passage buried in the middle is violated;
small packs hold trivially; the CLI exit codes are 0/1/2.
Run: python3 -m unittest discover -s scripts/tests -p 'test_wiki_packing_check.py'
"""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ask"))
import wiki_packing_check as m
import evidence_packing as ep

def passage(page, score):
    return {"page": page, "passage": "text-%s" % page, "score": score}

SIX = [passage("mid-b", .70), passage("strongest", .95), passage("weakest", .50),
       passage("second", .90), passage("mid-a", .80), passage("weak-second", .60)]

class T(unittest.TestCase):
    def test_packed_output_holds(self):
        result = ep.pack_evidence(list(SIX), budget=1000)
        self.assertTrue(result["lost_in_middle_applied"])
        check = m.check_pack(result["packed"])
        self.assertTrue(check["holds"], check)
        self.assertTrue(check["applied"])
    def test_buried_strongest_is_violated(self):
        # Relevance-descending order with NO rearrangement: the
        # second-strongest sits at position 1 (interior), not an end.
        buried = sorted(SIX, key=lambda p: -p["score"])
        check = m.check_pack(buried)
        self.assertFalse(check["holds"])
        self.assertTrue(check["problems"])
    def test_weakest_at_an_end_is_violated(self):
        packed = ep.pack_evidence(list(SIX), budget=1000)["packed"]
        packed[-1] = passage("weakest", .50)
        self.assertFalse(m.check_pack(packed)["holds"])
    def test_small_packs_hold_trivially(self):
        for n in (0, 1, 3):
            check = m.check_pack(SIX[:n])
            self.assertTrue(check["holds"]); self.assertFalse(check["applied"])
    def test_unscored_pack_cannot_be_checked(self):
        check = m.check_pack([{"page": "p%d" % i, "passage": "x"} for i in range(4)])
        self.assertFalse(check["holds"])
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "good.json"; bad = Path(d) / "bad.json"
            good.write_text(json.dumps(ep.pack_evidence(list(SIX), budget=1000)))
            bad.write_text(json.dumps({"packed": sorted(SIX, key=lambda p: -p["score"])}))
            self.assertEqual(m.main([str(good)]), 0)
            self.assertEqual(m.main([str(bad)]), 1)
            self.assertEqual(m.main([str(Path(d) / "missing.json")]), 2)
if __name__ == "__main__": unittest.main()
