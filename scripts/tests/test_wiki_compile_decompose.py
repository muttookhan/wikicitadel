#!/usr/bin/env python3
"""Tests for scripts/wiki_compile_decompose.py (Marathon R7 lane BA).
Run: python3 -m unittest scripts.tests.test_wiki_compile_decompose
"""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import wiki_compile_decompose as wcd  # noqa: E402

ROOT = SCRIPTS.parent
TH = {"lines": 50, "chars": 800, "sections": 3, "cite_markers": 5}
BIG = "# T\n\n" + "\n\n".join(
    f"## Section {i}\n\nClaim {i} was settled in 2026. ^[cite: raw/x.md#L{i}-L{i}]\n\nBody text for section {i} with enough words to matter here."
    for i in range(5))

class Decompose(unittest.TestCase):
    def test_data_file_prompts_per_class(self):
        data = wcd.load_data(ROOT)
        for cls in ("paper", "repo", "transcript", "filing", "generic"):
            self.assertGreaterEqual(len(data["validation_prompts"][cls]), 5)
        self.assertIn("chars", data["complexity_threshold"])
    def test_small_source_not_split(self):
        plan = wcd.decompose("## Only\n\nShort text.", TH)
        self.assertFalse(plan["split"]); self.assertEqual(len(plan["chunks"]), 1)
    def test_big_source_split_with_gather(self):
        plan = wcd.decompose(BIG, TH, "paper", "T")
        self.assertTrue(plan["split"]); self.assertGreaterEqual(len(plan["chunks"]), 4)
        second = plan["chunks"][1]
        self.assertEqual(second["gather"]["previous_section"], plan["chunks"][0]["section"])
        self.assertTrue(second["gather"]["prior_first_sentences"])
        self.assertTrue(second["gather"]["shared_terms"])

class Glean(unittest.TestCase):
    def test_glean_reports_missed(self):
        data = wcd.load_data(ROOT)
        prompts = data["validation_prompts"]["generic"]
        rep = wcd.glean(BIG, "## Section 0\n\nOnly this.", prompts)
        self.assertGreater(rep["missed_total"], 0)
        checks = {c["check"]: c for c in rep["checks"]}
        self.assertIn("Section 4", checks["sections"]["missed"])
        self.assertTrue(checks["citations"]["missed"])
        self.assertEqual(rep["checks"][0]["validation_prompt"], prompts[0])
    def test_glean_clean_compiled_reports_zero_sections(self):
        data = wcd.load_data(ROOT)
        rep = wcd.glean(BIG, BIG, data["validation_prompts"]["generic"])
        self.assertEqual({c["check"]: c for c in rep["checks"]}["sections"]["missed"], [])

if __name__ == "__main__":
    unittest.main()
