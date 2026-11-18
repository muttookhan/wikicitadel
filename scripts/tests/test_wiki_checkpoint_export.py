#!/usr/bin/env python3
"""Tests for scripts/wiki_checkpoint_export.py (B3 round).

On a fixture mini-tree: the package holds the selected pages
verbatim, the COVERAGE statement names the pages, their
sources, and the frontmatter date range; the OMISSIONS list
names exactly the linked-but-unselected pages; the manifest
hashes match the files; two runs are byte-identical
(deterministic); an unknown page is a usage error (exit 2)
and --out inside the tree is refused.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = "wiki_checkpoint_export.py"

ALPHA = """---
title: Alpha
type: entity
created: 2026-10-01
updated: 2026-10-05
sources:
  - raw/sources/alpha-note.md
---

# Alpha

Alpha rests on [[beta]] and [[gamma]].
"""

BETA = """---
title: Beta
type: entity
created: 2026-10-03
updated: 2026-10-04
sources:
  - raw/sources/beta-note.md
---

# Beta

Beta links back to [[alpha]].
"""

GAMMA = """---
title: Gamma
type: entity
created: 2026-10-02
updated: 2026-10-02
---

# Gamma
"""


class ExportFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckpt-export-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        wiki = self.tmp / "wiki" / "entities"
        wiki.mkdir(parents=True)
        (wiki / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (wiki / "beta.md").write_text(BETA, encoding="utf-8")
        (wiki / "gamma.md").write_text(GAMMA, encoding="utf-8")
        self.out = self.tmp.parent / (self.tmp.name + "-pkg")

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / TOOL), "--root",
             str(self.tmp), *args], capture_output=True, text=True)

    def export(self, out, *pages):
        return self.run_tool("--out", str(out), *pages)


class TestExport(ExportFixture):
    def test_package_contents_coverage_and_omissions(self):
        r = self.export(self.out, "wiki/entities/alpha.md",
                        "wiki/entities/beta.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Pages bundled verbatim.
        for name, text in (("alpha", ALPHA), ("beta", BETA)):
            bundled = (self.out / "pages" / "wiki" / "entities"
                       / f"{name}.md").read_text(encoding="utf-8")
            self.assertEqual(bundled, text)
        coverage = (self.out / "COVERAGE.md").read_text(
            encoding="utf-8")
        self.assertIn("wiki/entities/alpha.md", coverage)
        self.assertIn("raw/sources/alpha-note.md", coverage)
        self.assertIn("raw/sources/beta-note.md", coverage)
        self.assertIn("2026-10-01 to 2026-10-05", coverage)
        omissions = (self.out / "OMISSIONS.md").read_text(
            encoding="utf-8")
        self.assertIn("wiki/entities/gamma.md", omissions)
        self.assertIn("wiki/entities/alpha.md", omissions)
        self.assertNotIn("beta.md` (linked from", omissions)
        manifest = json.loads((self.out / "manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual([p["path"] for p in manifest["pages"]],
                         ["wiki/entities/alpha.md",
                          "wiki/entities/beta.md"])
        for rec in manifest["pages"]:
            data = (self.tmp / rec["path"]).read_bytes()
            self.assertEqual(rec["sha256"],
                             hashlib.sha256(data).hexdigest())
            self.assertEqual(rec["bytes"], len(data))
        self.assertEqual(manifest["omitted_pages"],
                         ["wiki/entities/gamma.md"])

    def test_deterministic_two_runs_byte_identical(self):
        out2 = self.tmp.parent / (self.tmp.name + "-pkg2")
        self.export(self.out, "wiki/entities/alpha.md")
        self.export(out2, "wiki/entities/alpha.md")
        for name in ("COVERAGE.md", "OMISSIONS.md",
                     "manifest.json"):
            self.assertEqual((self.out / name).read_bytes(),
                             (out2 / name).read_bytes(), name)

    def test_closed_selection_has_no_omitted_pages(self):
        r = self.export(self.out, "wiki/entities/alpha.md",
                        "wiki/entities/beta.md",
                        "wiki/entities/gamma.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        manifest = json.loads((self.out / "manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(manifest["omitted_pages"], [])

    def test_unknown_page_and_inside_out_refused(self):
        r = self.export(self.out, "wiki/entities/nope.md")
        self.assertEqual(r.returncode, 2)
        r = self.run_tool("--out", str(self.tmp / "pkg"),
                          "wiki/entities/alpha.md")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
