#!/usr/bin/env python3
"""Pins wiki_term_mine cohesion extraction. Run: discover -p 'test_wiki_term_mine.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_term_mine as m
class T(unittest.TestCase):
    def test_cohesive_term_found_random_not(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d); (r/"wiki").mkdir(); 
            (r/"wiki"/"a.md").write_text("verifiable history chain " * 6 + " scattered unrelated words appear once here")
            terms={c["term"] for c in m.mine(r,min_freq=3,min_cohesion=0.5)}
            self.assertIn("verifiable history",terms)
if __name__=="__main__": unittest.main()
