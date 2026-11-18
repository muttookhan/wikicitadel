import copy, importlib.util, json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_zaveri_coverage", ROOT / "scripts/wiki_zaveri_coverage.py")

class ZaveriCoverageTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "evaluation/zaveri-coverage.json").read_text())

    def test_canonical_list_is_23_in_six_groups(self):
        self.assertEqual(len(MOD.CANONICAL), 23)
        self.assertEqual(len({c for c, _d in MOD.CANONICAL}), 6)
        self.assertEqual(len({d for _c, d in MOD.CANONICAL}), 23)

    def test_seeded_register_is_complete_and_honest(self):
        self.assertEqual(MOD.check_register(self.data), [])
        rep = MOD.build_report(self.data)
        self.assertEqual(rep["rows"], 23)
        self.assertEqual(len(rep["covered"]), 7)
        self.assertEqual(len(rep["partial"]), 11)
        self.assertEqual([g["dimension"] for g in rep["gaps"]],
                         ["performance", "objectivity", "volatility",
                          "amount-of-data", "representational-conciseness"])

    def test_missing_row_and_duplicate_row_fail(self):
        d = copy.deepcopy(self.data); d["rows"] = d["rows"][:-1]
        self.assertTrue(any("no row for dimension" in e for e in MOD.check_register(d)))
        d = copy.deepcopy(self.data); d["rows"].append(copy.deepcopy(d["rows"][0]))
        self.assertTrue(any("duplicate row" in e for e in MOD.check_register(d)))

    def test_unknown_dimension_and_wrong_category_fail(self):
        d = copy.deepcopy(self.data); d["rows"][0]["dimension"] = "shininess"
        errs = MOD.check_register(d)
        self.assertTrue(any("not a Zaveri" in e for e in errs))
        d = copy.deepcopy(self.data); d["rows"][0]["category"] = "intrinsic"
        self.assertTrue(any("category" in e for e in MOD.check_register(d)))

    def test_gap_row_naming_a_check_and_partial_without_gap_note_fail(self):
        d = copy.deepcopy(self.data)
        gap = [r for r in d["rows"] if r["coverage"] == "gap"][0]
        gap["checks"] = ["scripts/wiki_validate.py"]
        self.assertTrue(any("gap row names checks" in e for e in MOD.check_register(d)))
        d = copy.deepcopy(self.data)
        part = [r for r in d["rows"] if r["coverage"] == "partial"][0]
        part["gap_note"] = ""
        self.assertTrue(any("partial row carries no gap_note" in e for e in MOD.check_register(d)))

    def test_nonexistent_named_check_fails(self):
        d = copy.deepcopy(self.data); d["rows"][1]["checks"] = ["scripts/wiki_no_such_check.py"]
        self.assertTrue(any("does not exist in this tree" in e for e in MOD.check_register(d)))

    def test_dimensions_list_tampering_fails(self):
        d = copy.deepcopy(self.data); d["dimensions"] = d["dimensions"][:-1]
        self.assertTrue(any("canonical" in e for e in MOD.check_register(d)))

    def test_check_exit_codes(self):
        self.assertEqual(MOD.main(["check"]), 0)
        self.assertEqual(MOD.main(["check", "--register", str(ROOT / "evaluation/nope.json")]), 1)

if __name__ == "__main__":
    unittest.main()
