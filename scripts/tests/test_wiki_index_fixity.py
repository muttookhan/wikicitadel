"""Tests for scripts/wiki_index_fixity.py (CN6a) — pins:
a derived index matches a filed index written from the same
derivation (no drift, exit-0 semantics); an unfiled page, a
stale entry, a misplaced entry, a duplicate and a summary
difference are each reported in their own class; --write
emits the proposal as a separate file and refuses to target
the filed index. Fixture trees in temp dirs only.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location(
    "wiki_index_fixity", HERE.parents[1] / "wiki_index_fixity.py")
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


def page(root, rel, title, body_line):
    p = root / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ntitle: {title}\ntype: concept\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\nsources: []\ntags: [demo]\n---\n\n"
        f"# {title}\n\n{body_line}\n", encoding="utf-8")
    return p


def make_root(tmp):
    root = Path(tmp) / "repo"
    (root / "wiki").mkdir(parents=True)
    page(root, "overview.md", "Overview", "The living overview line.")
    page(root, "concepts/alpha.md", "Alpha", "Alpha is a demo concept.")
    page(root, "sources/beta.md", "Beta", "Beta summarises a source.")
    (root / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    return root


class IndexFixityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _file_derived(self):
        report = fix.compare(self.root) if False else None
        pages = fix.scan_pages(self.root)
        (self.root / "wiki" / "index.md").write_text(
            fix.render_index(pages), encoding="utf-8")

    def test_clean_tree_no_structural_drift(self):
        self._file_derived()
        report = fix.compare(self.root)
        self.assertFalse(report["structural_drift"], report)
        self.assertTrue(report["identical"])
        self.assertEqual(report["pages_on_disk"], 3)
        self.assertEqual(report["unfiled_pages"], [])
        self.assertEqual(report["stale_entries"], [])

    def test_unfiled_and_stale(self):
        self._file_derived()
        page(self.root, "concepts/gamma.md", "Gamma", "Gamma is new.")
        idx = self.root / "wiki" / "index.md"
        text = idx.read_text(encoding="utf-8")
        idx.write_text(text + "\n- [[ghost]] — no such page\n",
                       encoding="utf-8")
        report = fix.compare(self.root)
        self.assertTrue(report["structural_drift"])
        self.assertEqual([p["stem"] for p in report["unfiled_pages"]],
                         ["gamma"])
        self.assertEqual(report["stale_entries"], ["ghost"])

    def test_misplaced_duplicate_and_summary_drift(self):
        self._file_derived()
        idx = self.root / "wiki" / "index.md"
        text = idx.read_text(encoding="utf-8")
        text = text.replace("- [[alpha]] — Alpha is a demo concept.",
                            "- [[alpha]] — A hand summary that moved.")
        # move beta's entry under Concepts by appending a duplicate
        text += "\n## Concepts\n\n- [[beta]] — Beta summarises a source.\n"
        idx.write_text(text, encoding="utf-8")
        report = fix.compare(self.root)
        self.assertEqual(report["duplicate_entries"], ["beta"])
        self.assertEqual(report["summary_drift_count"], 1)
        self.assertEqual(report["summary_drift"][0]["stem"], "alpha")
        # a lone entry filed under the wrong section is misplaced
        idx.write_text(
            "# Index\n\n## Sources\n\n"
            "- [[alpha]] — Alpha is a demo concept.\n"
            "- [[beta]] — Beta summarises a source.\n\n"
            "## Overview\n\n- [[overview]] — The living overview line.\n",
            encoding="utf-8")
        report = fix.compare(self.root)
        self.assertEqual([m["stem"] for m in report["misplaced"]],
                         ["alpha"])

    def test_write_proposal_separate_and_refuses_index(self):
        self._file_derived()
        out = Path(self._tmp.name) / "proposal.md"
        rc = fix.main(["x", "--root", str(self.root),
                       "--write", str(out)])
        self.assertEqual(rc, 0)
        self.assertTrue(out.is_file())
        self.assertIn("[[alpha]]", out.read_text(encoding="utf-8"))
        before = (self.root / "wiki" / "index.md").read_bytes()
        rc = fix.main(["x", "--root", str(self.root), "--write",
                       str(self.root / "wiki" / "index.md")])
        self.assertEqual(rc, 2)
        self.assertEqual((self.root / "wiki" / "index.md").read_bytes(),
                         before)


if __name__ == "__main__":
    unittest.main()
