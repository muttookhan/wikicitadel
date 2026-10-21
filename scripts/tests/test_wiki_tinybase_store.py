import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_tinybase_store", ROOT / "scripts/wiki_tinybase_store.py")
Store = MOD.MergeableStore

class TinyBaseStoreTests(unittest.TestCase):
    def test_seeded_store_valid_empty(self):
        obj, errs = MOD.load_store_file()
        self.assertEqual(errs, []); self.assertEqual(obj["tables"], {}); self.assertEqual(obj["checkpoints"], {})
    def test_set_get_and_stale_stamp_refused(self):
        s = Store(); self.assertTrue(s.set_cell("prefs", "ui", "theme", "dark", 2, "tool"))
        self.assertFalse(s.set_cell("prefs", "ui", "theme", "light", 1, "tool"))
        self.assertEqual(s.get_cell("prefs", "ui", "theme"), "dark")
        self.assertEqual(s.table_values("prefs"), {"ui": {"theme": "dark"}})
    def test_merge_keeps_greater_stamp_per_cell(self):
        a, b = Store(), Store()
        a.set_cell("t", "r", "c1", "a1", 1, "x"); a.set_cell("t", "r", "c2", "a2", 5, "x")
        b.set_cell("t", "r", "c1", "b1", 3, "y"); b.set_cell("t", "r", "c2", "b2", 2, "y")
        changed = a.merge(b)
        self.assertEqual(changed, 1)
        self.assertEqual(a.get_cell("t", "r", "c1"), "b1"); self.assertEqual(a.get_cell("t", "r", "c2"), "a2")
    def test_listeners_notified_and_failing_listener_recorded(self):
        s = Store(); seen = []
        s.add_listener(seen.append)
        s.add_listener(lambda c: (_ for _ in ()).throw(ValueError("boom")))
        s.set_cell("t", "r", "c", "v", 1, "x")
        self.assertEqual([c["op"] for c in seen], ["set"])
        self.assertEqual(len(s.listener_errors), 1); self.assertIn("ValueError", s.listener_errors[0]["error"])
        self.assertEqual(s.get_cell("t", "r", "c"), "v")
    def test_checkpoint_and_rollback_roundtrip(self):
        s = Store(); s.set_cell("t", "r", "c", "v1", 1, "x")
        cid = s.checkpoint("before")
        s.set_cell("t", "r", "c", "v2", 2, "x"); s.set_cell("t", "r2", "c", "new", 1, "x")
        self.assertTrue(s.rollback(cid)); self.assertEqual(s.get_cell("t", "r", "c"), "v1")
        self.assertIsNone(s.get_cell("t", "r2", "c")); self.assertFalse(s.rollback("cp-9999"))
    def test_save_load_preserves_checkpoints_and_hash_check(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"; s = Store(); s.set_cell("t", "r", "c", "v", 1, "x")
            cid = s.checkpoint("x"); s.save(p)
            back = Store.load(p); self.assertEqual(back.get_cell("t", "r", "c"), "v")
            self.assertIn(cid, back.checkpoints)
            obj = json.loads(p.read_text()); obj["checkpoints"][cid]["tables"] = {}
            p.write_text(json.dumps(obj))
            _o, errs = MOD.load_store_file(p); self.assertTrue(any("hash" in e for e in errs))
    def test_delete_row(self):
        s = Store(); s.set_cell("t", "r", "c", "v", 1, "x")
        self.assertTrue(s.delete_row("t", "r")); self.assertFalse(s.delete_row("t", "r"))

if __name__ == "__main__":
    unittest.main()
