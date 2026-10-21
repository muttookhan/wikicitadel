import importlib.util, json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_reservation_register", ROOT / "scripts/wiki_reservation_register.py")
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

def _rec(**kw):
    r = {"kind": "reservation", "agent": "lane-a", "glob": "scripts/wiki_*.py",
         "reserved_at": "2026-10-21T11:00:00Z", "expires": "2026-10-21T13:00:00Z",
         "note": "", "advisory_only": True}
    r.update(kw); return r

class ReservationRegisterTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        recs, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertEqual(recs, [])
        rep = MOD.build_report(at=NOW)
        self.assertEqual(rep["active"], 0); self.assertTrue(rep["advisory_only"])
    def test_record_then_active(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"; p.write_text('{"kind":"header"}\n')
            self.assertEqual(MOD.main(["record", "--agent", "lane-bb", "--glob",
                                       "evaluation/*.json", "--ttl-minutes", "60",
                                       "--register", str(p)]), 0)
            recs, errs = MOD.load_register(p); self.assertEqual(errs, [])
            self.assertEqual(recs[0]["agent"], "lane-bb")
            self.assertTrue(MOD.is_active(recs[0], at=MOD.now_utc()))
    def test_expire_splits_and_deletes_nothing(self):
        recs = [_rec(), _rec(agent="lane-b", glob="wiki/*.md",
                             expires="2026-10-21T11:30:00Z")]
        active, expired = MOD.expire(recs, at=NOW)
        self.assertEqual(len(active), 1); self.assertEqual(len(expired), 1)
        self.assertEqual(len(recs), 2)  # expire is report-only, input untouched
    def test_overlap_heuristic(self):
        self.assertTrue(MOD.globs_overlap("scripts/wiki_*.py", "scripts/wiki_loro_merge.py"))
        self.assertTrue(MOD.globs_overlap("scripts/*.py", "scripts/wiki_*.py"))
        self.assertFalse(MOD.globs_overlap("scripts/*.py", "wiki/*.md"))
        self.assertFalse(MOD.globs_overlap("evaluation/a.json", "evaluation/b.json"))
    def test_overlaps_reported_not_enforced_and_same_agent_ignored(self):
        recs = [_rec(), _rec(agent="lane-b", glob="scripts/wiki_loro_merge.py"),
                _rec(agent="lane-a", glob="scripts/wiki_*.py",
                     reserved_at="2026-10-21T11:05:00Z")]
        pairs = MOD.find_overlaps(recs, at=NOW)
        self.assertTrue(pairs); self.assertTrue(all(p["agents"] == ["lane-a", "lane-b"] or p["agents"] == ["lane-b", "lane-a"] for p in pairs))
        self.assertEqual(MOD.find_overlaps([recs[0], recs[2]], at=NOW), [])  # same agent: not an overlap
        # check still passes with an overlap present: advisory, blocks nothing
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
            self.assertEqual(MOD.main(["check", "--register", str(p)]), 0)
    def test_bad_records_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            p.write_text(json.dumps(_rec(expires="2026-10-21T10:00:00Z")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("after reserved_at" in e for e in errs))
            p.write_text(json.dumps(_rec(glob="")) + "\n")
            _r, errs = MOD.load_register(p); self.assertTrue(any("glob" in e for e in errs))
            self.assertEqual(MOD.main(["check", "--register", str(p)]), 1)
    def test_nonpositive_ttl_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.jsonl"
            self.assertEqual(MOD.main(["record", "--agent", "x", "--glob", "g",
                                       "--ttl-minutes", "0", "--register", str(p)]), 2)

if __name__ == "__main__":
    unittest.main()
