import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_publication_state", ROOT / "scripts/wiki_publication_state.py")

def _page(state=None):
    fm = "---\ntitle: T\ntype: concept\n"
    if state is not None:
        fm += f"publication_state: {state}\n"
    return fm + "---\n\n# T\n"

class PublicationStateTests(unittest.TestCase):
    def test_vocabulary_file_valid_and_closed(self):
        data, err = MOD.load_vocabulary()
        self.assertIsNone(err)
        self.assertEqual(MOD.validate_vocabulary(data), [])
        self.assertEqual([s["id"] for s in data["states"]],
                         ["share", "publish", "cite-ready"])
        self.assertEqual([t["id"] for t in data["publish_tests"]],
                         ["citability", "quality-control", "ethical-reuse"])
        self.assertEqual(data["field"], "publication_state")
    def test_publish_test_requires_all_three_legs(self):
        self.assertTrue(MOD.passes_publish_test(True, True, True))
        for legs in [(False, True, True), (True, False, True), (True, True, False)]:
            self.assertFalse(MOD.passes_publish_test(*legs))
    def test_vocabulary_tampering_detected(self):
        data, _err = MOD.load_vocabulary()
        broken = json.loads(json.dumps(data))
        broken["states"] = broken["states"][:2]
        self.assertTrue(any("state ids" in e for e in MOD.validate_vocabulary(broken)))
        broken2 = json.loads(json.dumps(data))
        broken2["publish_tests"] = []
        self.assertTrue(any("publish test" in e for e in MOD.validate_vocabulary(broken2)))
    def test_scan_counts_declared_invalid_undeclared(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "wiki").mkdir()
            (root / "wiki" / "a.md").write_text(_page("publish"))
            (root / "wiki" / "b.md").write_text(_page("share"))
            (root / "wiki" / "c.md").write_text(_page("Bogus"))
            (root / "wiki" / "d.md").write_text(_page())
            rep = MOD.build_report(root)
            self.assertEqual(rep["pages_scanned"], 4)
            self.assertEqual(len(rep["declared"]["publish"]), 1)
            self.assertEqual(len(rep["declared"]["share"]), 1)
            self.assertEqual(rep["invalid"], [{"page": "wiki/c.md", "value": "Bogus"}])
            self.assertEqual(rep["undeclared"], 1)
            self.assertEqual(MOD.main(["check", "--root", str(root)]), 1)
    def test_check_clean_fixture_and_statement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "wiki").mkdir()
            (root / "wiki" / "a.md").write_text(_page("cite-ready"))
            self.assertEqual(MOD.main(["check", "--root", str(root)]), 0)
        self.assertEqual(MOD.main(["statement", "publish"]), 0)
        self.assertEqual(MOD.main(["statement", "share"]), 0)

if __name__ == "__main__":
    unittest.main()
