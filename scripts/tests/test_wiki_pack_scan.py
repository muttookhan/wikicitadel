"""Tests for scripts/wiki_pack_scan.py and its wiring into
scripts/wiki_bag.py pack — pins: a clean payload scans clean
and packs; a payload carrying a credential-shaped pattern
(a synthetic AKIA-shaped string, not a real credential) is
found by class+count only (the matched value appears
nowhere in the report), REFUSES the pack with nothing
copied, packs under allow_pack_findings with the scan in
the stats, and packs with scan=False only as a recorded
skip. Fixture trees in temp dirs only.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan = load("wiki_pack_scan")
bag = load("wiki_bag")

# Synthetic pattern shape only, assembled from fragments so
# the literal never appears in the tree (the validator scans
# the tree itself for secret shapes — writing it out would
# trip the very check this test exercises).
FAKE = "AK" + "IA" + "1234567890" + "ABCDEF"


def make_root(tmp, dirty=False):
    root = Path(tmp) / "repo"
    (root / "wiki").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "wiki" / "index.md").write_text("# Index\n",
                                            encoding="utf-8")
    body = "ordinary page text\n"
    if dirty:
        body += f"an example key shape: {FAKE}\n"
    (root / "wiki" / "page.md").write_text(body, encoding="utf-8")
    (root / "evaluation" / "r.jsonl").write_text('{"a": 1}\n',
                                                 encoding="utf-8")
    (root / "AGENTS.md").write_text("schema\n", encoding="utf-8")
    return root


class PackScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_set_scans_clean(self):
        root = make_root(self._tmp.name)
        report = scan.scan_set(root, "compiled")
        self.assertEqual(report["verdict"], "clean")
        self.assertEqual(report["findings_total"], 0)
        self.assertGreaterEqual(report["files_scanned"], 3)

    def test_hit_reported_by_class_only(self):
        root = make_root(self._tmp.name, dirty=True)
        report = scan.scan_set(root, "compiled")
        self.assertEqual(report["verdict"], "findings")
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["findings"][0]["file"], "wiki/page.md")
        self.assertNotIn(FAKE, json.dumps(report))

    def test_pack_refused_and_nothing_copied(self):
        root = make_root(self._tmp.name, dirty=True)
        dest = Path(self._tmp.name) / "out" / "bag"
        with self.assertRaises(ValueError) as ctx:
            bag.pack(root, dest, "compiled", bagging_date="2026-10-21")
        self.assertIn("pack refused", str(ctx.exception))
        self.assertNotIn(FAKE, str(ctx.exception))
        self.assertFalse((dest / "data").exists())

    def test_pack_allowed_with_warnings_in_stats(self):
        root = make_root(self._tmp.name, dirty=True)
        dest = Path(self._tmp.name) / "out" / "bag"
        stats = bag.pack(root, dest, "compiled",
                         bagging_date="2026-10-21",
                         allow_pack_findings=True)
        self.assertEqual(stats["pack_scan"]["findings_total"], 1)
        ok, problems, _ = bag.validate(dest)
        self.assertTrue(ok, problems)

    def test_pack_scan_skip_is_recorded(self):
        root = make_root(self._tmp.name, dirty=True)
        dest = Path(self._tmp.name) / "out" / "bag"
        stats = bag.pack(root, dest, "compiled",
                         bagging_date="2026-10-21", scan=False)
        self.assertEqual(stats["pack_scan"]["verdict"], "skipped")

    def test_clean_pack_stats_show_clean_scan(self):
        root = make_root(self._tmp.name)
        dest = Path(self._tmp.name) / "out" / "bag"
        stats = bag.pack(root, dest, "compiled",
                         bagging_date="2026-10-21")
        self.assertEqual(stats["pack_scan"]["verdict"], "clean")


if __name__ == "__main__":
    unittest.main()
