import copy, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_crdt_pattern", ROOT / "scripts/wiki_crdt_pattern.py")

def _set(reg, key, value, clock, actor):
    return {"op": "set", "register": reg, "key": key, "value": value, "clock": clock, "actor": actor}

class CrdtPatternTests(unittest.TestCase):
    def test_seed_document_valid_and_empty(self):
        doc = json.loads((ROOT / "evaluation/crdt-pattern-register.json").read_text())
        self.assertEqual(MOD.validate_document(doc), [])
        self.assertEqual(doc["registers"], {})
        self.assertIn("write topology is NOT changed", doc["boundary"])

    def test_lww_newest_wins_and_actor_breaks_ties(self):
        d = MOD.apply_ops(MOD.new_document(), [
            _set("r", "k", "v1", 1, "alice"), _set("r", "k", "v2", 2, "alice")])
        self.assertEqual(MOD.live_entries(d, "r"), {"k": "v2"})
        d2 = MOD.apply_ops(MOD.new_document(), [
            _set("r", "k", "alice", 2, "alice"), _set("r", "k", "bob", 2, "bob")])
        d3 = MOD.apply_ops(MOD.new_document(), [
            _set("r", "k", "bob", 2, "bob"), _set("r", "k", "alice", 2, "alice")])
        self.assertEqual(MOD.live_entries(d2, "r"), {"k": "bob"})
        self.assertEqual(d2, d3)  # order does not matter

    def test_tombstone_beats_older_set_newer_set_revives(self):
        d = MOD.apply_ops(MOD.new_document(), [
            _set("r", "k", "v", 1, "a"),
            {"op": "delete", "register": "r", "key": "k", "clock": 3, "actor": "a"},
            _set("r", "k", "stale", 2, "a")])
        self.assertEqual(MOD.live_entries(d, "r"), {})
        d = MOD.apply_op(d, _set("r", "k", "revived", 4, "a"))
        self.assertEqual(MOD.live_entries(d, "r"), {"k": "revived"})

    def test_add_wins_set(self):
        d = MOD.apply_ops(MOD.new_document(), [
            {"op": "add", "register": "s", "member": "x", "clock": 1, "actor": "a"},
            {"op": "remove", "register": "s", "member": "x", "clock": 2, "actor": "a"}])
        self.assertEqual(MOD.live_entries(d, "s"), [])
        d = MOD.apply_op(d, {"op": "add", "register": "s", "member": "x", "clock": 2, "actor": "b"})
        self.assertEqual(MOD.live_entries(d, "s"), ["x"])  # concurrent add wins

    def test_merge_is_commutative_associative_idempotent(self):
        base, da, db = MOD.demo_document_pair()
        a, b = MOD.apply_ops(base, da), MOD.apply_ops(base, db)
        c = MOD.apply_ops(base, [{"op": "add", "register": "tags", "member": "crdt",
                                  "clock": 5, "actor": "carol"}])
        self.assertEqual(MOD.merge(a, b), MOD.merge(b, a))
        self.assertEqual(MOD.merge(MOD.merge(a, b), c), MOD.merge(a, MOD.merge(b, c)))
        self.assertEqual(MOD.merge(a, a), a)
        self.assertEqual(MOD.merge(a, MOD.new_document()), a)

    def test_demo_converges_to_stated_live_state(self):
        base, da, db = MOD.demo_document_pair()
        merged = MOD.merge(MOD.apply_ops(base, da), MOD.apply_ops(base, db))
        self.assertEqual(MOD.live_entries(merged, "reading-list"), {"paper-a": "skimmed"})
        self.assertEqual(MOD.live_entries(merged, "tags"), ["lod", "quality"])

    def test_inputs_never_mutated(self):
        d = MOD.apply_ops(MOD.new_document(), [_set("r", "k", "v", 1, "a")])
        before = copy.deepcopy(d)
        MOD.apply_op(d, _set("r", "k", "v2", 2, "a"))
        MOD.merge(d, MOD.new_document())
        self.assertEqual(d, before)

    def test_register_kind_conflict_and_bad_op_rejected(self):
        a = MOD.apply_ops(MOD.new_document(), [_set("r", "k", "v", 1, "a")])
        b = MOD.apply_ops(MOD.new_document(), [
            {"op": "add", "register": "r", "member": "x", "clock": 1, "actor": "a"}])
        with self.assertRaises(ValueError):
            MOD.merge(a, b)
        with self.assertRaises(ValueError):
            MOD.apply_op(MOD.new_document(), {"op": "frobnicate", "register": "r",
                                              "clock": 1, "actor": "a"})

    def test_validate_rejects_malformed_entry(self):
        doc = {"kind": "crdt-register-document", "registers": {
            "r": {"kind": "lww-map", "entries": {"k": {"value": 1}}}}}
        self.assertTrue(MOD.validate_document(doc))

    def test_cli_check_merge_apply_demo(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            a = MOD.apply_ops(MOD.new_document(), [_set("r", "k", "va", 1, "alice")])
            b = MOD.apply_ops(MOD.new_document(), [_set("r", "k2", "vb", 1, "bob")])
            (td / "a.json").write_text(json.dumps(a)); (td / "b.json").write_text(json.dumps(b))
            self.assertEqual(MOD.main(["check", str(td / "a.json")]), 0)
            self.assertEqual(MOD.main(["merge", str(td / "a.json"), str(td / "b.json"),
                                       "--out", str(td / "m.json")]), 0)
            merged = json.loads((td / "m.json").read_text())
            self.assertEqual(MOD.live_entries(merged, "r"), {"k": "va", "k2": "vb"})
            (td / "ops.json").write_text(json.dumps({"ops": [
                {"op": "delete", "register": "r", "key": "k", "clock": 9, "actor": "z"}]}))
            self.assertEqual(MOD.main(["apply", str(td / "m.json"), str(td / "ops.json"),
                                       "--out", str(td / "m2.json")]), 0)
            self.assertEqual(MOD.live_entries(json.loads((td / "m2.json").read_text()), "r"),
                             {"k2": "vb"})
            self.assertEqual(MOD.main(["demo"]), 0)
            self.assertEqual(MOD.main(["check", str(td / "nope.json")]), 2)

if __name__ == "__main__":
    unittest.main()
