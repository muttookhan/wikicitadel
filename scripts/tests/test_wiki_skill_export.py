#!/usr/bin/env python3
"""Phase-2 harvest item 10: Skill Factory export (pattern:
VectifyAI/OpenKB, Apache-2.0). The package lands OUTSIDE the
wiki page layer, carries a hashed manifest bound to the source
commit, and versions append-only.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_skill_export", ROOT / "scripts" / "wiki_skill_export.py")
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)

PAGE = """---
title: {title}
type: concept
created: 2030-10-01
updated: 2030-10-01
sources: []
tags: [fixture]
---

{title} lede paragraph with real words in it.
"""


class TestSkillExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "wiki" / "concepts").mkdir(parents=True)
        (self.root / "wiki" / "access").mkdir(parents=True)
        (self.root / "wiki" / "overview.md").write_text(
            PAGE.format(title="Overview"), encoding="utf-8")
        (self.root / "wiki" / "concepts" / "alpha.md").write_text(
            PAGE.format(title="Alpha"), encoding="utf-8")
        (self.root / "wiki" / "index.md").write_text("# Index\n",
                                                    encoding="utf-8")
        (self.root / "wiki" / "access" / "ledger.md").write_text(
            "# secret ledger\n", encoding="utf-8")
        (self.root / "purpose.md").write_text("The purpose.\n",
                                              encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c",
                        "user.email=t@t", "-c", "user.name=T",
                        "commit", "-q", "-m", "fixture"], capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_package_shape_manifest_and_exclusions(self):
        out = se.build_export(self.root)
        self.assertEqual(out.name, "skill-v1")
        skill = (out / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: wikicitadel", skill)
        self.assertIn("The purpose.", skill)
        self.assertIn("Alpha", skill)
        manifest = json.loads((out / "manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(manifest["version"], 1)
        self.assertTrue(manifest["source_commit"])
        self.assertEqual(manifest["page_count"], 2)  # overview + alpha
        # Manifest hashes verify against the shipped bytes.
        for rel, digest in manifest["files"].items():
            data = (out / rel).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, rel)
        # Access records and structural machinery are NOT pages here.
        shipped = list((out / "pages").rglob("*.md"))
        names = {p.name for p in shipped}
        self.assertNotIn("ledger.md", names)
        self.assertNotIn("index.md", names)

    def test_versions_are_append_only(self):
        se.build_export(self.root)
        out2 = se.build_export(self.root)
        self.assertEqual(out2.name, "skill-v2")
        self.assertTrue((self.root / "exports" / "skill-v1").is_dir())


if __name__ == "__main__":
    unittest.main()
