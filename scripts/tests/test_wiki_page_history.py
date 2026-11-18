#!/usr/bin/env python3
"""Tests for wiki_page_history. Pins log parsing and diff capture with a fake runner (no real git needed)."""
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("ph",ROOT/"scripts/wiki_page_history.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def fake(cmd):
    if "-p" in cmd: return "diff --git a/x b/x\n+line\n"
    return "abc123\t2026-01-01T00:00:00+00:00\tFixture\tinit\n def456\t2026-01-02T00:00:00+00:00\tFixture\tsecond\n".replace(" def","def")
class T(unittest.TestCase):
    def test_parse(self):
        rows=m.git_log("/x","wiki/a.md",fake); self.assertEqual(len(rows),2); self.assertEqual(rows[0]["commit"],"abc123")
    def test_build(self):
        r=Path(tempfile.mkdtemp()); p=r/"wiki/a.md"; p.parent.mkdir(parents=True); p.write_text("hi")
        d=m.build(r,fake); self.assertEqual(d["pages"]["wiki/a.md"]["commits"],2); self.assertIn("+line",d["pages"]["wiki/a.md"]["latest_diff"])
    def test_empty_log(self):
        rows=m.git_log("/x","wiki/a.md",lambda c:""); self.assertEqual(rows,[])
if __name__=="__main__": unittest.main()
