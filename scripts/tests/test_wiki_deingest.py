#!/usr/bin/env python3
"""Phase-2 harvest item 8: de-ingest cascade (pattern:
VectifyAI/OpenKB, Apache-2.0). The plan is complete and hashed;
a dry run deletes nothing; execution requires an owner
authorisation bound to the exact plan hash; raw/ is never
touched by the tool, even on execute.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_deingest", ROOT / "scripts" / "wiki_deingest.py")
di = importlib.util.module_from_spec(spec)
spec.loader.exec_module(di)

PAGE = """---
title: {title}
type: source
created: 2030-10-01
updated: 2030-10-01
sources: [{sources}]
tags: [fixture]
---

Body of {title}.
"""


class TestDeingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for sub in ("raw/sources", "wiki/sources", "evaluation/pageindex"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "raw/sources/doc-a.md").write_text("A\n", encoding="utf-8")
        (self.root / "raw/sources/doc-b.md").write_text("B\n", encoding="utf-8")
        (self.root / "wiki/sources/only-a.md").write_text(
            PAGE.format(title="Only A", sources="raw/sources/doc-a.md"),
            encoding="utf-8")
        (self.root / "wiki/sources/mixed.md").write_text(
            PAGE.format(title="Mixed",
                        sources="raw/sources/doc-a.md, raw/sources/doc-b.md"),
            encoding="utf-8")
        (self.root / "wiki/sources/only-b.md").write_text(
            PAGE.format(title="Only B", sources="raw/sources/doc-b.md"),
            encoding="utf-8")
        (self.root / "wiki/index.md").write_text(
            "# Index\n\n- [[only-a]] — Only A\n- [[only-b]] — Only B\n",
            encoding="utf-8")
        (self.root / "evaluation/pageindex/doc-a.json").write_text(
            "{}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_is_complete_and_hash_stable(self):
        plan = di.compute_plan(self.root, "raw/sources/doc-a.md")
        self.assertEqual(plan["remove_pages"], ["wiki/sources/only-a.md"])
        self.assertEqual(plan["review_pages"], ["wiki/sources/mixed.md"])
        self.assertEqual(len(plan["index_entries"]), 1)
        self.assertEqual(plan["pageindex"],
                         ["evaluation/pageindex/doc-a.json"])
        self.assertTrue(any("owner only" in a
                            for a in plan["owner_actions"]))
        again = di.compute_plan(self.root, "raw/sources/doc-a.md")
        self.assertEqual(plan["plan_sha256"], again["plan_sha256"])

    def test_execute_requires_matching_owner_authorisation(self):
        plan = di.compute_plan(self.root, "raw/sources/doc-a.md")
        with self.assertRaises(SystemExit):
            di.execute_plan(self.root, plan,
                            {"plan_sha256": "deadbeef",
                             "authorised_by": "owner"})
        with self.assertRaises(SystemExit):
            di.execute_plan(self.root, plan,
                            {"plan_sha256": plan["plan_sha256"],
                             "authorised_by": "agent"})
        # Both refusals deleted nothing.
        self.assertTrue((self.root / "wiki/sources/only-a.md").exists())

    def test_execute_removes_derived_state_but_never_raw(self):
        plan = di.compute_plan(self.root, "raw/sources/doc-a.md")
        done = di.execute_plan(self.root, plan,
                               {"plan_sha256": plan["plan_sha256"],
                                "authorised_by": "owner"})
        self.assertTrue(done)
        self.assertFalse((self.root / "wiki/sources/only-a.md").exists())
        self.assertFalse((self.root / "evaluation/pageindex/doc-a.json")
                         .exists())
        self.assertTrue((self.root / "wiki/sources/mixed.md").exists())
        self.assertTrue((self.root / "wiki/sources/only-b.md").exists())
        index = (self.root / "wiki/index.md").read_text(encoding="utf-8")
        self.assertNotIn("[[only-a]]", index)
        self.assertIn("[[only-b]]", index)
        # raw/ untouched, by construction and in fact:
        self.assertTrue((self.root / "raw/sources/doc-a.md").exists())


if __name__ == "__main__":
    unittest.main()
