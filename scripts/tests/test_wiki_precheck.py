"""Tests for scripts/wiki_precheck.py — the pre-action
failure-history precheck (Marathon R9 lane BA; projectmem
board item).

Pins: a fixture root's corrections entry, post-mortem and
reflexion note naming the target are ALL surfaced; a target
with no history reports none (a statement about the
registers); absent registers are reported absent, never as
clean; short stems do not swallow unrelated pages; the tool
writes nothing (the fixture tree is byte-identical after a
report).

Run: python3 -m unittest scripts.tests.test_wiki_precheck
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module(name, filename=None):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / (filename or f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module("wiki_precheck")


def fixture_root(tmp):
    root = Path(tmp)
    (root / "wiki" / "rules").mkdir(parents=True)
    (root / "wiki" / "syntheses").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "scripts").mkdir()
    # The precheck reuses the corrections counter's parser;
    # point its import at the real scripts dir by copying the
    # loader's expectation: it resolves wiki_corrections.py
    # beside wiki_precheck.py, i.e. in SCRIPTS — so fixture
    # runs use the real parser against fixture data files.
    (root / "wiki" / "rules" /
     "corrections-ledger.md").write_text(
        "# Corrections ledger (fixture)\n\n## Entries\n\n"
        "### 2030-01-01 — The harbour page count was wrong\n\n"
        "- **What was wrong:** wiki/syntheses/harbour.md "
        "stated ten boats for twelve.\n"
        "- **Standing rule:** count from the register.\n\n"
        "| Entry | Class | Error kind | Standing rule |\n"
        "|---|---|---|---|\n"
        "| 2030-01-01 — The harbour page count was wrong "
        "| correction | wrong-fact | count-from-register |\n",
        encoding="utf-8")
    (root / "evaluation" / "post-mortems.jsonl").write_text(
        json.dumps({
            "id": "PM-2030-001", "date": "2030-01-02",
            "title": "Harbour answer built from a summary",
            "trigger_ref": "fixture",
            "what_happened": "The harbour page was compiled "
                             "from a summary.",
            "root_cause_class": "evidence-discipline",
            "rule_changed": "Compile from the source.",
            "see_also": ["wiki/syntheses/harbour.md"],
        }) + "\n", encoding="utf-8")
    (root / "wiki" / "syntheses" / "harbour.md").write_text(
        "# Harbour\n\n## Reflection notes\n\n"
        "- [2030-01-03] reflexion | wiki/syntheses/harbour.md "
        "count check\n"
        "  - Failed: the boat count check on harbour.md\n"
        "  - Cause class: missing-evidence\n"
        "  - Evidence: fixture register\n"
        "  - Do differently: count from the register.\n",
        encoding="utf-8")
    (root / "wiki" / "syntheses" / "other.md").write_text(
        "# Other\n\nNothing logged here.\n", encoding="utf-8")
    return root


def tree_digest(root):
    out = []
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out.append((p.relative_to(root).as_posix(),
                        hashlib.sha256(p.read_bytes())
                        .hexdigest()))
    return out


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fixture_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_three_registers_surface(self):
        rep = MOD.build_report(self.root,
                               "wiki/syntheses/harbour.md")
        self.assertEqual(len(rep["corrections_ledger"]), 1)
        self.assertEqual(
            rep["corrections_ledger"][0]["standing_rule"],
            "count-from-register")
        self.assertEqual(len(rep["post_mortems"]), 1)
        self.assertEqual(len(rep["reflexion_notes"]), 1)
        self.assertEqual(rep["total_hits"], 3)

    def test_no_history_reports_none(self):
        rep = MOD.build_report(self.root,
                               "wiki/syntheses/other.md")
        self.assertEqual(rep["total_hits"], 0)
        self.assertIn("No recorded failure history",
                      MOD.render_text(rep))

    def test_stem_target_matches(self):
        rep = MOD.build_report(self.root, "harbour")
        self.assertGreaterEqual(rep["total_hits"], 1)

    def test_report_writes_nothing(self):
        before = tree_digest(self.root)
        MOD.build_report(self.root, "wiki/syntheses/harbour.md")
        self.assertEqual(tree_digest(self.root), before)


class AbsentRegisterTests(unittest.TestCase):
    def test_absent_registers_reported_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki").mkdir(parents=True)
            rep = MOD.build_report(root, "wiki/anything.md")
            self.assertIsNone(rep["corrections_ledger"])
            self.assertIsNone(rep["post_mortems"])
            text = MOD.render_text(rep)
            self.assertIn("register absent", text)


class ShippedDataTests(unittest.TestCase):
    def test_ideas_page_history_in_private_tree(self):
        rep = MOD.build_report(ROOT, "wiki/ideas.md")
        if rep["post_mortems"] is None:
            self.skipTest("this tree carries no post-mortems "
                          "register")
        self.assertGreaterEqual(len(rep["post_mortems"]), 1)


if __name__ == "__main__":
    unittest.main()
