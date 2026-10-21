#!/usr/bin/env python3
"""Tests for Lens citation augmentation + git provenance
(Marathon R7 lane BA; CiteSee / Memoize patterns).
Run: python3 -m unittest tools.lens.tests.test_citation_augmentation
"""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))
import lenslib as L  # noqa: E402

def _repo(td):
    root = Path(td)
    (root/"evaluation").mkdir(parents=True)
    (root/"raw").mkdir()
    src = root/"raw/s.md"; src.write_text("line one\nline two\n")
    block = ["line one", "line two"]
    lock = {"citations": [
        {"id": "c1", "page": "wiki/a.md", "page_line": 3, "claim": "Claim one.",
         "source": "raw/s.md", "range": [1, 2],
         "content_hash": hashlib.sha256("\n".join(block).encode()).hexdigest(),
         "line_hashes": [], "selector": {"exact": "line one"}},
        {"id": "c2", "page": "wiki/b.md", "page_line": 5, "claim": "Claim two.",
         "source": "raw/s.md", "range": [1, 2],
         "content_hash": hashlib.sha256("\n".join(block).encode()).hexdigest(),
         "line_hashes": [], "selector": {"exact": "line two"}}]}
    (root/"evaluation/citation-lockfile.json").write_text(json.dumps(lock))
    (root/"evaluation/treatment-register.jsonl").write_text(
        json.dumps({"kind": "treatment", "id": "t1", "date": "2026-10-19",
                    "subject": {"page": "wiki/a.md", "claim": None},
                    "grade": "negative"}) + "\n")
    return root

class Augmentation(unittest.TestCase):
    def test_standing_from_registers(self):
        with tempfile.TemporaryDirectory() as td:
            aug = L.citation_augmentation(_repo(td))
            s = aug["wiki/a.md"]["c1"]
            self.assertEqual(s["reliance_count"], 2)
            self.assertEqual(s["treatment"], "negative")
            self.assertEqual(s["treatment_date"], "2026-10-19")
            self.assertFalse(s["cited_text_changed"])
            self.assertIsNone(s["cited_text_changed_date"])
    def test_changed_text_detected_and_dated(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(td)
            (root/"raw/s.md").write_text("line one EDITED\nline two\n")
            aug = L.citation_augmentation(root, changed_dates={"raw/s.md": "2026-10-20"})
            s = aug["wiki/a.md"]["c1"]
            self.assertTrue(s["cited_text_changed"])
            self.assertEqual(s["cited_text_changed_date"], "2026-10-20")
    def test_no_treatment_is_none_not_invented(self):
        with tempfile.TemporaryDirectory() as td:
            aug = L.citation_augmentation(_repo(td))
            self.assertEqual(aug["wiki/b.md"]["c2"]["treatment"], "none")

class Provenance(unittest.TestCase):
    def test_edit_link_one_prefix(self):
        cfg = {"edit_link_prefix": "https://example.com/edit/"}
        self.assertEqual(L.edit_link_for("wiki/a.md", cfg), "https://example.com/edit/wiki/a.md")
        self.assertEqual(L.edit_link_for("wiki/a.md", {}), "wiki/a.md")
    def test_git_provenance_fake_runner(self):
        prov = L.git_provenance("repo", "wiki/a.md", runner=lambda r, p: "2026-10-20T01:02:03+00:00\tA Person\n")
        self.assertEqual(prov, {"last_modified": "2026-10-20", "last_author": "A Person"})
        empty = L.git_provenance("repo", "wiki/x.md", runner=lambda r, p: "")
        self.assertEqual(empty, {"last_modified": None, "last_author": None})
    def test_config_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(L.load_lens_config(Path(td))["edit_link_prefix"], "")

if __name__ == "__main__":
    unittest.main()
