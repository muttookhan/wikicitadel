#!/usr/bin/env python3
"""Pins wiki_manual_bound_invocation: manual change invalidates. Run: discover -p 'test_wiki_manual_bound_invocation.py'"""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_manual_bound_invocation as m
class T(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); self.r=Path(self.d); (self.r/"AGENTS.md").write_text("manual v1")
    def test_roundtrip(self):
        tok=m.issue(self.r,"agent-a",b"test-secret",now=1000)
        self.assertEqual(m.verify(self.r,tok,b"test-secret",now=1000),(True,"ok"))
    def test_manual_change_invalidates(self):
        tok=m.issue(self.r,"agent-a",b"test-secret",now=1000); (self.r/"AGENTS.md").write_text("manual v2")
        self.assertEqual(m.verify(self.r,tok,b"test-secret",now=1000)[1],"manual-changed")
    def test_wrong_secret_and_expiry(self):
        tok=m.issue(self.r,"agent-a",b"test-secret",now=1000)
        self.assertFalse(m.verify(self.r,tok,b"other",now=1000)[0])
        self.assertEqual(m.verify(self.r,tok,b"test-secret",max_age_days=1,now=1000+2*86400)[1],"expired")
if __name__=="__main__": unittest.main()
