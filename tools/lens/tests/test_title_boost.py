#!/usr/bin/env python3
"""Lens test path for the exact-title/stem-match boost (Marathon
Round 3, lane TB7, row 1).

Pins, on fixtures (never the live corpus):
  - lenslib's PostingsIndex hybrid applies the boost with the
    same constants as scripts/wiki_search.py;
  - the Lens client's app.js carries the TITLE-BOOST block, the
    hybrid lane consumes it, and — when node is available — the
    extracted pure JS functions return the Python values for
    the probe cases (exact / stem / none). Without node the JS
    execution sub-test is skipped, never faked.

Run:  python3 -m unittest discover -s tools/lens/tests
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
REPO = HERE.parents[3]
sys.path.insert(0, str(LENS_DIR))

import lenslib as L  # noqa: E402

APP_JS = LENS_DIR / "assets" / "app.js"

DOCS = [
    {"key": "/x/wiki/zebra.md",
     "text": "---\ntitle: Zebra\n---\n# Zebra\n\nzebra once.\n"},
    {"key": "/x/wiki/filler.md",
     "text": "---\ntitle: Filler\n---\n# Filler\n\n"
             + "zebra " * 30 + "\n"},
]


class LenslibBoostTests(unittest.TestCase):
    def test_constants_match_python(self):
        src = (REPO / "scripts" / "wiki_search.py").read_text()
        self.assertIn(f"TITLE_EXACT_BOOST = {L.TITLE_EXACT_BOOST}", src)
        self.assertIn(f"TITLE_STEM_BOOST = {L.TITLE_STEM_BOOST}", src)

    def test_hybrid_applies_boost(self):
        idx = L.PostingsIndex(DOCS)
        adj = {0: [], 1: []}
        ranked = idx.hybrid_rank(L.tokenize("zebra"), adj)
        self.assertEqual(Path(idx.docs[ranked[0][1]]["key"]).name,
                         "zebra.md")
        self.assertEqual(ranked[0][2]["title_match"], "exact")
        self.assertEqual(ranked[0][2]["title_boost"], 10.0)


class AppJsBoostTests(unittest.TestCase):
    def test_block_present_and_consumed(self):
        src = APP_JS.read_text(encoding="utf-8")
        self.assertIn("TITLE-BOOST-BEGIN", src)
        self.assertIn("TITLE-BOOST-END", src)
        self.assertIn("function titleBoostJs(", src)
        self.assertIn("function stemTokenJs(", src)
        self.assertIn("titleBoostJs(queryTerms, SEARCH.docs[di].title",
                      src)
        self.assertIn("title_boost: tb.boost", src)

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_js_functions_match_python_values(self):
        lines = APP_JS.read_text(encoding="utf-8").splitlines()
        start = next(i for i, ln in enumerate(lines)
                     if "const TITLE_EXACT_BOOST" in ln)
        end = next(i for i, ln in enumerate(lines)
                   if "TITLE-BOOST-END" in ln)
        block = "\n".join(lines[start:end])
        pre = ('const TOKEN_RE = /[a-z0-9]+/g;\n'
               'function tokenize(text){return (String(text)'
               '.toLowerCase().match(TOKEN_RE)||[])'
               '.filter(t=>t.length>=2);}\n')
        probe = (pre + block + "\nconsole.log(JSON.stringify(["
                 "titleBoostJs(['galen'],'Galen','galen'),"
                 "titleBoostJs(['running'],'Run','run'),"
                 "titleBoostJs(['zebra'],'Filler','filler'),"
                 "stemTokenJs('studies')]));\n")
        with tempfile.TemporaryDirectory() as td:
            probe_file = Path(td) / "probe.js"
            probe_file.write_text(probe, encoding="utf-8")
            out = subprocess.run(["node", str(probe_file)],
                                 capture_output=True, text=True,
                                 timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout.strip())
        self.assertEqual(got[0], {"boost": 10, "kind": "exact"})
        self.assertEqual(got[1], {"boost": 5, "kind": "stem"})
        self.assertEqual(got[2], {"boost": 0, "kind": None})
        self.assertEqual(got[3], "study")
        # and the Python mirror agrees on the same probes
        self.assertEqual(L.title_boost_value(["galen"], "Galen", "galen"),
                         (10.0, "exact"))
        self.assertEqual(L.title_boost_value(["running"], "Run", "run"),
                         (5.0, "stem"))
        self.assertEqual(L.stem_token("studies"), "study")


if __name__ == "__main__":
    unittest.main()
