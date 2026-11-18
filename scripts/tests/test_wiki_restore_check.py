#!/usr/bin/env python3
"""Tests for scripts/wiki_restore_check.py — restore verification
(consolidated queue item 25, 2030-10-20).

Fixture strategy: a minimal fake wiki in a zip — stub scripts
standing in for the real tools (a stub that exits 0 and prints
the search header shape), so the orchestration is what is under
test: zip integrity first (a corrupted member is named and the
restore stops), extraction into a fresh dir, every check's
verdict reported, and the restore counting only when all pass.
One regression test pins the first real run's lesson: the search
header is parsed from the FULL output, never a truncated tail
(the 2030-10-20 run reported a healthy 135-hit query as 0 hits
because the capture was tail-truncated before the parse).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_restore_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_restore_check_under_test", SCRIPTS / "wiki_restore_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rc = load_restore_module()

STUB_OK = "import sys\nsys.exit(0)\n"
STUB_FAIL = "import sys\nprint('stub failure')\nsys.exit(1)\n"
# Header at the TOP, then >600 chars of body: the parse must see
# the header (the truncation regression).
STUB_SEARCH = (
    "import sys\n"
    "print('Query: stub  corpus=3 docs')\n"
    "print('Hits: 7 (showing 3)')\n"
    "print('x' * 900)\n"
)


def _fake_wiki_zip(base, fail_tool=None, corrupt=False):
    """Zip a minimal wiki-shaped tree under prefix miniwiki/."""
    files = {
        "scripts/wiki_provenance.py": STUB_OK,
        "scripts/wiki_cite_lock.py": STUB_OK,
        "scripts/wiki_validate.py": STUB_OK,
        "scripts/wiki_search.py": STUB_SEARCH,
        "wiki/pages/page-a.md": "page a\n",
    }
    if fail_tool:
        files[f"scripts/{fail_tool}"] = STUB_FAIL
    zpath = Path(base) / "mini.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:
        for rel, text in files.items():
            zf.writestr(f"miniwiki/{rel}", text)
    if corrupt:
        # Flip bytes inside the stored page member's data: its CRC
        # no longer matches, so testzip must name the member.
        data = bytearray(zpath.read_bytes())
        idx = data.find(b"page a\n")
        assert idx > 0
        data[idx] = ord("X")
        zpath.write_bytes(bytes(data))
    return zpath


class TestRestoreCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="restore-test-")
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_healthy_fixture_counts(self):
        report = rc.restore_and_check(_fake_wiki_zip(self.base))
        self.assertTrue(report["counts"], report["checks"])
        names = [c["name"] for c in report["checks"]]
        self.assertIn("zip integrity (CRC)", names)
        self.assertIn("validator", names)

    def test_search_header_parsed_from_full_output(self):
        report = rc.restore_and_check(_fake_wiki_zip(self.base),
                                      queries=("anything",))
        smoke = [c for c in report["checks"]
                 if c["name"].startswith("search smoke")]
        self.assertEqual(len(smoke), 1)
        self.assertTrue(smoke[0]["ok"])
        self.assertIn("hits 7", smoke[0]["detail"])

    def test_failing_tool_fails_the_restore(self):
        report = rc.restore_and_check(
            _fake_wiki_zip(self.base, fail_tool="wiki_validate.py"))
        self.assertFalse(report["counts"])
        bad = [c for c in report["checks"] if not c["ok"]]
        self.assertEqual([c["name"] for c in bad], ["validator"])

    def test_corrupt_member_named_and_stops_the_restore(self):
        zpath = _fake_wiki_zip(self.base, corrupt=True)
        ok, bad, _count = rc.check_zip_integrity(zpath)
        self.assertFalse(ok)
        self.assertEqual(bad, "miniwiki/wiki/pages/page-a.md")
        report = rc.restore_and_check(zpath)
        self.assertFalse(report["counts"])
        # Only the integrity check ran — a corrupt zip is not restored.
        self.assertEqual(len(report["checks"]), 1)
        self.assertIn("page-a.md", report["checks"][0]["detail"])

    def test_find_wiki_root(self):
        inner = self.base / "outer" / "miniwiki"
        (inner / "scripts").mkdir(parents=True)
        (inner / "scripts" / "wiki_validate.py").write_text(STUB_OK)
        self.assertEqual(rc.find_wiki_root(self.base / "outer"), inner)
        self.assertIsNone(rc.find_wiki_root(self.base))


if __name__ == "__main__":
    unittest.main()
