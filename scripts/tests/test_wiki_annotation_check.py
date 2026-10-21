import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = _load("wiki_annotation_check", ROOT / "scripts/wiki_annotation_check.py")
GOOD = {"@context": "http://www.w3.org/ns/anno.jsonld", "id": "anno-1", "type": "Annotation",
        "body": [{"type": "TextualBody", "value": "a note", "purpose": "commenting"}],
        "target": {"source": "image.png", "selector": {"type": "FragmentSelector",
                   "conformsTo": "http://www.w3.org/TR/media-frags/", "value": "xywh=10,10,100,50"}}}

class AnnotationTests(unittest.TestCase):
    def test_good_annotation_valid(self):
        self.assertEqual(MOD.check_annotation(GOOD, "t"), [])
    def test_missing_context_and_target_rejected(self):
        errs = MOD.check_annotation({"type": "Annotation", "id": "x"}, "t")
        self.assertTrue(any("@context" in e for e in errs)); self.assertTrue(any("target" in e for e in errs))
    def test_bad_xywh_rejected(self):
        bad = json.loads(json.dumps(GOOD)); bad["target"]["selector"]["value"] = "xywh=abc"
        self.assertTrue(MOD.check_annotation(bad, "t"))
    def test_check_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.json"; p.write_text(json.dumps([GOOD]))
            errs, n = MOD.check_file(p); self.assertEqual(errs, []); self.assertEqual(n, 1)
            self.assertEqual(MOD.main(["check", str(p)]), 0)

if __name__ == "__main__":
    unittest.main()
