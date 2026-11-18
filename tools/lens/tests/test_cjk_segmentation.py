#!/usr/bin/env python3
"""Lens test path for CJK search-mode segmentation (Marathon
Round 4, lane B, item 2).

Pins: lenslib.tokenize emits the whole CJK run plus its
character bigrams (the mirror of scripts/wiki_search.py), and --
when node is available -- the Lens client's app.js tokenize
block returns the identical stream for the probe strings.
Without node the JS sub-test is skipped, never faked.

Run:  python3 -m unittest discover -s tools/lens/tests
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
sys.path.insert(0, str(LENS_DIR))

import lenslib as L  # noqa: E402

APP_JS = LENS_DIR / "assets" / "app.js"
PROBES = ["東京都の検索エンジン", "Hello 東京都 world", "猫",
          "한국어검색", "plain english 42 x"]


class CjkLensTests(unittest.TestCase):
    def test_lenslib_whole_and_bigrams(self):
        toks = L.tokenize("東京都の検索エンジン")
        self.assertEqual(toks[0], "東京都の検索エンジン")
        self.assertIn("検索", toks)
        self.assertIn("京都", toks)

    @unittest.skipUnless(shutil.which("node"), "node unavailable")
    def test_app_js_tokenize_matches_python(self):
        src = APP_JS.read_text(encoding="utf-8")
        m = re.search(r"const TOKEN_RE.*?function firstTermOffset"
                      r"\([^)]*\)\s*\{.*?\n\}", src, re.S)
        self.assertIsNotNone(m, "app.js CJK tokenize block missing")
        js = (m.group(0) + "\nconsole.log(JSON.stringify("
              "PROBES.map(p => tokenize(p))));")
        js = "const PROBES = " + json.dumps(
            PROBES, ensure_ascii=False) + ";\n" + js
        out = subprocess.run(["node", "-e", js], capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout.strip().splitlines()[-1])
        want = [L.tokenize(p) for p in PROBES]
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
