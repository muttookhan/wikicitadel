#!/usr/bin/env python3
"""Tests for scripts/wiki_worktypes.py — type-of-work labels
(consolidated-queue item 16).

The classifier is deterministic over observable signals; the
apply step may add ONLY work_type/methods frontmatter lines,
must never touch a body, and must never overwrite a work_type
a page already carries.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wt = load("wiki_worktypes")


def sig(**over):
    base = {
        "path": "wiki/sources/x.md", "type": "source", "status": "",
        "tags": [], "sources_n": 1, "cites_n": 0, "existing": {},
    }
    base.update(over)
    return base


class ClassifyTests(unittest.TestCase):
    def test_single_source_page_is_record(self):
        work_type, _ = wt.classify(sig(sources_n=1))
        self.assertEqual(work_type, "record")

    def test_multi_source_page_is_synthesis(self):
        work_type, _ = wt.classify(sig(sources_n=4))
        self.assertEqual(work_type, "synthesis")

    def test_design_synthesis_is_speculation(self):
        work_type, _ = wt.classify(sig(
            path="wiki/syntheses/big-design.md", type="synthesis",
            tags=["design"], sources_n=5))
        self.assertEqual(work_type, "speculation")

    def test_rules_page_is_advice_ledger_is_record(self):
        work_type, _ = wt.classify(sig(path="wiki/rules/x.md"))
        self.assertEqual(work_type, "advice")
        work_type, _ = wt.classify(
            sig(path="wiki/rules/corrections-ledger.md"))
        self.assertEqual(work_type, "record")

    def test_ideas_board_is_advice(self):
        work_type, _ = wt.classify(sig(path="wiki/ideas.md",
                                       type="synthesis"))
        self.assertEqual(work_type, "advice")

    def test_existing_work_type_never_reclassified(self):
        work_type, reason = wt.classify(sig(
            path="wiki/sources/x.md", sources_n=9,
            existing={"work_type": "record"}))
        self.assertEqual(work_type, "record")
        self.assertIn("never overwritten", reason)

    def test_query_page_needs_both_signals_for_synthesis(self):
        work_type, _ = wt.classify(sig(
            path="wiki/queries/q.md", type="query",
            sources_n=3, cites_n=4))
        self.assertEqual(work_type, "record")
        work_type, _ = wt.classify(sig(
            path="wiki/queries/q.md", type="query",
            sources_n=3, cites_n=5))
        self.assertEqual(work_type, "synthesis")

    def test_methods_only_for_synthesis_and_advice(self):
        s = sig(sources_n=2)
        self.assertIsNotNone(wt.methods_for("synthesis", s))
        self.assertIsNotNone(wt.methods_for("advice", s))
        self.assertIsNone(wt.methods_for("record", s))
        self.assertIsNone(wt.methods_for("speculation", s))


class ApplyFieldTests(unittest.TestCase):
    PAGE = ("---\ntitle: X\ntype: source\n---\n\n"
            "# X\n\nBody text that must not change.\n")

    def test_adds_missing_fields_body_untouched(self):
        new_text, added = wt.add_worktype_fields(
            self.PAGE, {"work_type": "record", "methods": None})
        self.assertEqual(added, ["work_type"])
        self.assertIn("work_type: record", new_text)
        _, body_before = wt.split_frontmatter(self.PAGE)
        _, body_after = wt.split_frontmatter(new_text)
        self.assertEqual(body_before, body_after)
        self.assertEqual(wt.body_hash(self.PAGE),
                         wt.body_hash(new_text))

    def test_existing_work_type_never_overwritten(self):
        page = self.PAGE.replace("type: source",
                                 "type: source\nwork_type: advice")
        new_text, added = wt.add_worktype_fields(
            page, {"work_type": "record",
                   "methods": "A proposed methods line."})
        self.assertIn("work_type: advice", new_text)
        self.assertNotIn("work_type: record", new_text)
        self.assertEqual(added, ["methods"])

    def test_no_frontmatter_no_change(self):
        text = "# Plain\n\nNo frontmatter here.\n"
        new_text, added = wt.add_worktype_fields(
            text, {"work_type": "record"})
        self.assertEqual(new_text, text)
        self.assertEqual(added, [])


if __name__ == "__main__":
    unittest.main()
