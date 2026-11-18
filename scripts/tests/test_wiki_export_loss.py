"""Tests for scripts/wiki_export_loss.py (Marathon R11 lane BB)."""
import importlib.util, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
def load():
    s = importlib.util.spec_from_file_location("wiki_export_loss", SCRIPTS / "wiki_export_loss.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
MOD = load()

class T(unittest.TestCase):
    def _corpus(self, td):
        root = Path(td); (root / "wiki").mkdir(parents=True)
        (root / "wiki" / "a.md").write_text(
            "# A\n\nLinks [[b]] and [[ghost-page]].\n\n![[img.png]]\n\n"
            "> [!warning] Careful\n\nClaim. ^[cite: raw/x.md#L1]\n\n"
            "Flag {{cite}} here.\n\n<div>html</div>\n")
        (root / "wiki" / "b.md").write_text("# B\n\nClean.\n")
        (root / "wiki" / "index.md").write_text("# Index [[ghost-page]]\n")
        return root

    def test_inventory_counts_loss(self):
        with tempfile.TemporaryDirectory() as td:
            inv = MOD.inventory(self._corpus(td))
            t = inv["totals"]
            self.assertEqual(t["pages"], 2)  # index.md excluded
            self.assertEqual(t["unresolved_wikilinks"], 1)
            self.assertEqual(t["embeds"], 1)
            self.assertEqual(t["callouts"], 1)
            self.assertEqual(t["claim_markers"], 1)
            self.assertEqual(t["editorial_markers"], 1)
            self.assertIn("ghost-page", inv["unresolved_targets"])

    def test_report_is_never_a_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._corpus(td)
            rc = MOD.main(["inventory", "--root", str(root),
                           "--out-json", str(Path(td) / "i.json"),
                           "--out-md", str(Path(td) / "i.md")])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "i.md").is_file())

if __name__ == "__main__":
    unittest.main()
