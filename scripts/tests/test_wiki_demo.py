#!/usr/bin/env python3
"""Tests for scripts/wiki_demo.py — smoke against a tiny fixture site."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki_demo  # noqa: E402


class TestSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        site = Path(self.tmp.name)
        (site / "index.html").write_text("<html><body>demo</body></html>",
                                         encoding="utf-8")
        (site / "search-index.json").write_text('{"docs": []}',
                                                encoding="utf-8")
        self.httpd = wiki_demo.serve_in_thread(site, 0)
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.tmp.cleanup()

    def test_smoke_passes_on_fixture(self):
        checks = dict(wiki_demo.smoke(f"http://127.0.0.1:{self.port}"))
        self.assertTrue(checks["index"])
        self.assertTrue(checks["search-index"])

    def test_smoke_missing_search_index_is_skip_not_fail(self):
        (Path(self.tmp.name) / "search-index.json").unlink()
        checks = dict(wiki_demo.smoke(f"http://127.0.0.1:{self.port}"))
        self.assertTrue(checks["index"])
        self.assertIsNone(checks["search-index"])


if __name__ == "__main__":
    unittest.main()
