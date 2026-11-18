"""Tests for wiki_placeholders.py + wiki_link_refs.py (R9 BB)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load(name):
    s = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
PH = load("wiki_placeholders")
LR = load("wiki_link_refs")
class PlaceholdersTests(unittest.TestCase):
    def test_synthetic_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "wiki").mkdir()
            (root / "wiki" / "a.md").write_text(
                "---\ntitle: A\n---\nSee [[missing-page]] and [[b]].\n", encoding="utf-8")
            (root / "wiki" / "b.md").write_text(
                "---\ntitle: B\n---\nBody.\n", encoding="utf-8")
            rep = PH.placeholders(root)
            self.assertIn("missing-page", rep["placeholders"])
            self.assertEqual(rep["placeholders"]["missing-page"], ["wiki/a.md"])
            self.assertNotIn("b", rep["placeholders"])
    def test_real_tree_report_only(self):
        rep = PH.placeholders()
        self.assertEqual(rep["dangling_links_total"],
                         sum(len(v) for v in rep["placeholders"].values()))
        self.assertEqual(PH.main([]), 0)
class LinkRefsTests(unittest.TestCase):
    def test_convert_basic_and_label(self):
        text, defs = LR.convert("See [[concepts/x]] and [[y|Why]].\n")
        self.assertIn("[concepts/x][ref-1]", text)
        self.assertIn("[Why][ref-2]", text)
        self.assertIn("[ref-1]: concepts/x.md", text)
        self.assertEqual(len(defs), 2)
    def test_code_never_converted_and_dedup(self):
        src = "`[[x]]`\n\n```\n[[y]]\n```\n\n[[z]] [[z]]\n"
        text, defs = LR.convert(src)
        self.assertIn("`[[x]]`", text); self.assertIn("[[y]]", text)
        self.assertEqual(len(defs), 1)
    def test_export_option_default_off(self):
        exp = load("wiki_export")
        plain = exp.render_marp(exp.ROOT, ["overview"] if (exp.ROOT / "wiki/overview.md").is_file() else [])
        self.assertIsInstance(plain, str)
if __name__ == "__main__":
    unittest.main()
