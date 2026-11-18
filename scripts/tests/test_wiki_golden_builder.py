#!/usr/bin/env python3
"""Pins wiki_golden_builder: verification + golden set byte-untouched + no overwrite.
Run: discover -p 'test_wiki_golden_builder.py'"""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_golden_builder as m
class T(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); self.r=Path(self.d); (self.r/"src").mkdir()
        (self.r/"src"/"a.md").write_text("# A\n\nThe verifiable history chain records every version of a document in order. Another sufficiently long sentence about archival practice and provenance follows here.")
        self.golden=self.r/"golden-questions.jsonl"; self.golden.write_text('{"q":"keep me"}\n'); self.h=hashlib.sha256(self.golden.read_bytes()).hexdigest()
    def test_build_and_golden_untouched(self):
        out=self.r/"candidates.jsonl"; rc=m.main(["--source-dir",str(self.r/"src"),"--out",str(out)])
        self.assertEqual(rc,0); rows=[json.loads(l) for l in out.read_text().splitlines()]
        self.assertTrue(any(r["answerable"] for r in rows)); self.assertTrue(any(not r["answerable"] for r in rows))
        self.assertTrue(all(r["verified"] for r in rows))
        self.assertEqual(hashlib.sha256(self.golden.read_bytes()).hexdigest(),self.h)
    def test_refuses_golden_and_existing(self):
        self.assertEqual(m.main(["--source-dir",str(self.r/"src"),"--out",str(self.golden)]),4)
        self.assertEqual(hashlib.sha256(self.golden.read_bytes()).hexdigest(),self.h)
class MiluT(T):
    def test_built_candidates_speak_source_terms(self):
        rows=m.build(self.r/"src")
        ans=[r for r in rows if r["answerable"]]
        self.assertTrue(ans); self.assertTrue(all(not r["milu_flagged"] for r in ans))
        self.assertTrue(all(r["milu_missing_terms"]==[] for r in ans))
    def test_foreign_terms_are_flagged(self):
        src=(self.r/"src"/"a.md").read_text()
        cand={"question":"What is stated about: quantum banana teleportation?","source":"a.md","answerable":True}
        findings=m.check_milu([cand],{"a.md":src})
        self.assertEqual(len(findings),1)
        self.assertIn("quantum",findings[0]["missing_terms"])
        self.assertIn("banana",findings[0]["missing_terms"])
    def test_decoys_exempt_and_missing_source_flagged(self):
        decoy={"question":"What does the corpus say about photosynthetic zebras?","source":None,"answerable":False}
        self.assertEqual(m.check_milu([decoy],{}),[])
        orphan={"question":"What is stated about: archival provenance?","source":"nope.md","answerable":True}
        self.assertTrue(m.check_milu([orphan],{}))
    def test_milu_check_cli_exit_codes(self):
        import json as j
        good=self.r/"good.jsonl"; bad=self.r/"bad.jsonl"
        good.write_text(j.dumps({"question":"What is stated about: verifiable history chain?","source":"a.md","answerable":True})+"\n")
        bad.write_text(j.dumps({"question":"What is stated about: quantum banana teleportation?","source":"a.md","answerable":True})+"\n")
        self.assertEqual(m.main(["--milu-check",str(good),"--source-dir",str(self.r/"src")]),0)
        self.assertEqual(m.main(["--milu-check",str(bad),"--source-dir",str(self.r/"src")]),1)
if __name__=="__main__": unittest.main()
