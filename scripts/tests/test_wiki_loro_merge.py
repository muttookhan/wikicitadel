import importlib.util, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_loro_merge", ROOT / "scripts/wiki_loro_merge.py")

def _e(v, c, a, deleted=False):
    return {"value": v, "counter": c, "actor": a, "deleted": deleted}

class LoroMergeTests(unittest.TestCase):
    def test_seeded_register_valid_empty(self):
        obj, errs = MOD.load_register()
        self.assertEqual(errs, []); self.assertTrue(obj["pattern_only"])
        self.assertEqual(obj["state"]["parents"], {}); self.assertEqual(obj["state"]["map"], {})
    def test_lww_higher_counter_wins_and_actor_breaks_ties(self):
        a = {"k": _e("old", 1, "lane-a")}
        b = {"k": _e("new", 2, "lane-a")}
        self.assertEqual(MOD.merge_lww_map(a, b)["k"]["value"], "new")
        c = {"k": _e("from-b", 2, "lane-b")}
        self.assertEqual(MOD.merge_lww_map(b, c)["k"]["value"], "from-b")
        self.assertEqual(MOD.merge_lww_map(a, {}), a)
    def test_tombstone_wins_and_stays_in_state(self):
        a = {"k": _e("live", 1, "lane-a")}
        b = {"k": _e(None, 3, "lane-b", deleted=True)}
        merged = MOD.merge_lww_map(a, b)
        self.assertIn("k", merged); self.assertTrue(merged["k"]["deleted"])
        self.assertEqual(MOD.live_map(merged), {})
    def test_move_replay_and_cycle_loses(self):
        base = {"r": None, "a": "r", "b": "r", "c": "a"}
        moves_a = [{"node": "b", "parent": "a", "counter": 1, "actor": "lane-a"}]
        # moving a under c (its own descendant) must lose as a cycle
        moves_b = [{"node": "a", "parent": "c", "counter": 2, "actor": "lane-b"}]
        parents, rejected = MOD.merge_tree(base, moves_a, moves_b)
        self.assertEqual(parents["b"], "a"); self.assertEqual(parents["a"], "r")
        self.assertEqual(len(rejected), 1); self.assertEqual(rejected[0]["reason"], "cycle")
    def test_missing_move_loses(self):
        parents, rejected = MOD.merge_tree({"r": None},
            [{"node": "ghost", "parent": "r", "counter": 1, "actor": "x"}], [])
        self.assertEqual(parents, {"r": None}); self.assertEqual(rejected[0]["reason"], "missing node or parent")
    def test_merge_state_is_deterministic(self):
        a = {"parents": {"r": None, "a": "r"}, "moves": [], "map": {"a": _e("A", 1, "x")}}
        b = {"parents": {"r": None, "a": "r", "b": "r"}, "moves": [], "map": {"b": _e("B", 1, "y")}}
        self.assertEqual(MOD.merge_state(a, b), MOD.merge_state(b, a))
    def test_shallow_snapshot_shape_no_inlined_children(self):
        state = {"parents": {"r": None, "a": "r", "b": "a"},
                 "moves": [], "map": {"a": _e("Title A", 1, "x"), "b": _e("Title B", 1, "x")}}
        snap = MOD.shallow_snapshot(state)
        self.assertEqual(snap["roots"], ["r"]); self.assertEqual(snap["nodes"]["r"]["child_count"], 1)
        self.assertEqual(snap["nodes"]["a"]["child_count"], 1)
        self.assertNotIn("children", snap["nodes"]["a"]); self.assertEqual(snap["map_keys"], ["a", "b"])
        self.assertEqual(snap, MOD.shallow_snapshot(state))
        changed = {"parents": state["parents"], "moves": [], "map": {"a": _e("Other", 2, "x"), "b": _e("Title B", 1, "x")}}
        self.assertNotEqual(snap["state_hash"], MOD.shallow_snapshot(changed)["state_hash"])

if __name__ == "__main__":
    unittest.main()
