"""Tests for scripts/wiki_bench_registry.py (Marathon R9 lane BB)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
def load():
    s = importlib.util.spec_from_file_location("wiki_bench_registry", SCRIPTS / "wiki_bench_registry.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()
class BenchRegistryTests(unittest.TestCase):
    def test_shipped_sidecar_shape(self):
        data = json.loads((ROOT / "evaluation/bench-reproducibility.json").read_text(encoding="utf-8"))
        self.assertEqual(data["kind"], "bench-registry")
        for rel, e in data["datasets"].items():
            self.assertTrue(e["reproducibility"] is None or e["reproducibility"] in MOD.LEVELS, rel)
    def test_check_covers_all_and_traced_or_null(self):
        rep = MOD.check()
        self.assertEqual(rep["total"], len(MOD.discover()))
        self.assertEqual(rep["graded"] + rep["ungraded"], rep["total"])
    def test_traced_or_null_violation_detected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "set.jsonl").write_text("{}\n", encoding="utf-8")
            side = base / "bench-reproducibility.json"
            side.write_text(json.dumps({"datasets": {"set.jsonl": {
                "reproducibility": "bogus", "source": None,
                "upstream": "someone", "upstream_url": None,
                "paper": None, "dataset_url": None}}}), encoding="utf-8")
            rep = MOD.check(base, side)
            self.assertTrue(any("traced-or-null" in f for f in rep["findings"]))
            self.assertTrue(any("closed vocabulary" in f for f in rep["findings"]))
    def test_generate_all_null(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); (base / "a.json").write_text("{}", encoding="utf-8")
            data = MOD.generate(base, base / "out.json")
            self.assertIsNone(data["datasets"]["a.json"]["reproducibility"])
if __name__ == "__main__":
    unittest.main()
