#!/usr/bin/env python3
"""Tests for scripts/wiki_skill_governance.py (build-list
wave 5, 2026-10-22 — Skill governance pack).

Pins, on fixture record strings + a temp tree:
  - the governance-block grammar: flow + block lists, the
    review mapping, history as a list of flat mappings,
    quoted scalars carrying colons;
  - the closed transition table enforced exactly: a legal
    lifecycle (proposed -> active -> deprecated -> active
    -> retired, reviews recorded) validates clean;
  - violations named: illegal transitions (including any
    exit from terminal retired), unrecorded activation /
    reactivation reviews, a destructive skill activated
    without owner approval, missing fields, unknown
    states, empty scope, chain breaks, state mismatch,
    date regressions, unparseable blocks;
  - census: SKILL.md records found by form, raw/ and .git
    excluded, undeclared records carry no violations;
  - the register is byte-deterministic across builds and
    `check`/`census` leave the tree byte-identical;
  - CLI: check exits 1 exactly when violations exist,
    register writes an artefact equal to the in-memory
    render.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    path = SCRIPTS / "wiki_skill_governance.py"
    spec = importlib.util.spec_from_file_location(
        "wiki_skill_governance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()

LEGAL = """---
name: demo-skill
description: "A fixture skill."
governance:
  state: retired
  proposed_by: mehmed
  evidence: "diagnosis: three failures on the fixed task sample"
  scope: [traverse-door, mcp-read-door]
  destructive: false
  review:
    state: current
    by: owner
    date: 2026-10-22
    evidence: "owner review in chat"
  history:
    - to: proposed
      by: mehmed
      date: 2026-10-20
      evidence: "candidate scaffolded from the failure diagnosis"
    - from: proposed
      to: active
      by: owner
      date: 2026-10-21
      evidence: "paired screen: 1.24x baseline on the task sample"
      review: "owner approval recorded in chat 2026-10-21"
    - from: active
      to: deprecated
      by: mehmed
      date: 2026-10-21
      evidence: "superseded by demo-skill v2"
    - from: deprecated
      to: active
      by: owner
      date: 2026-10-22
      evidence: "v2 recalled; v1 reinstated"
      review: "recorded review act 2026-10-22"
    - from: active
      to: retired
      by: owner
      date: 2026-10-22
      evidence: "v2 re-adopted; v1 retired for good"
---

# Demo skill
"""

UNDECLARED = """---
name: plain-skill
description: No governance block at all.
---

# Plain
"""


def gov_of(text):
    fm = MOD.split_frontmatter(text)
    return MOD.parse_governance(fm)


def violations_of(text):
    return MOD.validate_governance(gov_of(text))


def variant(old, new, text=LEGAL):
    assert old in text
    return text.replace(old, new, 1)


class GrammarTests(unittest.TestCase):
    def test_full_block_parses(self):
        gov = gov_of(LEGAL)
        self.assertEqual(gov["state"], "retired")
        self.assertEqual(gov["scope"],
                         ["traverse-door", "mcp-read-door"])
        self.assertEqual(gov["review"]["state"], "current")
        self.assertEqual(len(gov["history"]), 5)
        self.assertEqual(gov["history"][1]["to"], "active")
        # quoted scalar with a colon survives whole
        self.assertEqual(
            gov["evidence"],
            "diagnosis: three failures on the fixed task sample")

    def test_block_list_scope(self):
        text = variant("  scope: [traverse-door, mcp-read-door]",
                       "  scope:\n    - traverse-door\n"
                       "    - mcp-read-door")
        self.assertEqual(gov_of(text)["scope"],
                         ["traverse-door", "mcp-read-door"])

    def test_no_block_is_none(self):
        self.assertIsNone(gov_of(UNDECLARED))

    def test_unparseable_block_raises(self):
        text = variant("  state: retired",
                       "  state retired")
        with self.assertRaises(MOD.GovParseError):
            gov_of(text)


class ValidationTests(unittest.TestCase):
    def test_legal_lifecycle_is_clean(self):
        self.assertEqual(violations_of(LEGAL), [])

    def test_empty_block_reports_every_missing_field(self):
        names = violations_of("---\nname: x\ngovernance:\n---\n")
        self.assertEqual(names, [
            "missing-field:evidence", "missing-field:history",
            "missing-field:proposed_by", "missing-field:review",
            "missing-field:scope", "missing-field:state"])

    def test_unknown_state_and_empty_scope(self):
        text = variant("  state: retired", "  state: archived")
        text = variant("  scope: [traverse-door, mcp-read-door]",
                       "  scope: []", text)
        names = violations_of(text)
        self.assertIn("unknown-state:archived", names)
        self.assertIn("empty-scope", names)

    def test_illegal_transition_proposed_to_deprecated(self):
        text = variant("- from: proposed\n      to: active",
                       "- from: proposed\n      to: deprecated")
        names = violations_of(text)
        self.assertIn("illegal-transition:proposed->deprecated@1",
                      names)

    def test_retired_is_terminal(self):
        text = LEGAL.replace(
            '  state: retired', '  state: active').replace(
            '      evidence: "v2 re-adopted; v1 retired for good"',
            '      evidence: "v2 re-adopted; v1 retired for good"\n'
            '    - from: retired\n'
            '      to: active\n'
            '      by: owner\n'
            '      date: 2026-10-22\n'
            '      evidence: "an attempted resurrection"\n'
            '      review: "recorded"')
        names = violations_of(text)
        self.assertIn("illegal-transition:retired->active@5", names)

    def test_unrecorded_activation_review(self):
        text = variant('      review: "owner approval recorded '
                       'in chat 2026-10-21"\n', "")
        self.assertIn("unrecorded-activation-review@1",
                      violations_of(text))

    def test_unrecorded_reactivation_review(self):
        text = variant('      review: "recorded review act '
                       '2026-10-22"\n', "")
        self.assertIn("unrecorded-reactivation-review@3",
                      violations_of(text))

    def test_destructive_activation_needs_owner_approval(self):
        text = variant("  destructive: false", "  destructive: true")
        names = violations_of(text)
        self.assertIn(
            "destructive-activation-without-owner-approval@1", names)
        # reactivation of a destructive skill needs it too
        self.assertIn(
            "destructive-activation-without-owner-approval@3", names)
        ok = variant('      review: "owner approval recorded in '
                     'chat 2026-10-21"',
                     '      review: "owner approval recorded in '
                     'chat 2026-10-21"\n      approved_by: owner',
                     text)
        ok = variant('      review: "recorded review act '
                     '2026-10-22"',
                     '      review: "recorded review act '
                     '2026-10-22"\n      approved_by: owner', ok)
        self.assertEqual(violations_of(ok), [])

    def test_chain_break_and_state_mismatch(self):
        text = variant("- from: deprecated\n      to: active",
                       "- from: active\n      to: active")
        names = violations_of(text)
        self.assertIn("history-chain-break@3", names)
        text2 = variant("  state: retired", "  state: active")
        self.assertIn("history-state-mismatch",
                      violations_of(text2))

    def test_date_regression_and_bad_date(self):
        text = variant("      date: 2026-10-21\n"
                       "      evidence: \"superseded by demo-skill v2\"",
                       "      date: 2026-10-19\n"
                       "      evidence: \"superseded by demo-skill v2\"")
        self.assertIn("history-date-regression@2",
                      violations_of(text))
        text2 = variant("    date: 2026-10-22\n"
                        "    evidence: \"owner review in chat\"",
                        "    date: 22-10-2026\n"
                        "    evidence: \"owner review in chat\"")
        self.assertIn("bad-date:22-10-2026@review",
                      violations_of(text2))

    def test_history_not_birth_first(self):
        text = variant("    - to: proposed", "    - to: active")
        self.assertIn("history-not-birth-first",
                      violations_of(text))


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def tree_digest(root):
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


class TreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write(self.root, "tools/demo/SKILL.md", LEGAL)
        write(self.root, "tools/plain/SKILL.md", UNDECLARED)
        write(self.root, "exports/skill-v9/SKILL.md", UNDECLARED)
        write(self.root, "raw/sources/foreign/SKILL.md", LEGAL)
        write(self.root, ".git/hidden/SKILL.md", LEGAL)

    def tearDown(self):
        self._tmp.cleanup()

    def test_census_forms_and_exclusions(self):
        reg = MOD.build_register(self.root)
        self.assertEqual(reg["records_total"], 3)
        forms = {r["path"]: r["form"] for r in reg["records"]}
        self.assertEqual(forms["tools/demo/SKILL.md"], "tool-skill")
        self.assertEqual(forms["exports/skill-v9/SKILL.md"],
                         "generated-export")
        self.assertEqual(reg["governed_total"], 1)
        self.assertEqual(reg["violations_total"], 0)
        plain = [r for r in reg["records"]
                 if r["name"] == "plain-skill"][0]
        self.assertEqual(plain["governance"], "undeclared")
        self.assertEqual(plain["violations"], [])

    def test_register_is_byte_deterministic(self):
        first = MOD.render_register(MOD.build_register(self.root))
        second = MOD.render_register(MOD.build_register(self.root))
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["content_hash"],
                         json.loads(second)["content_hash"])

    def test_check_and_census_write_nothing(self):
        before = tree_digest(self.root)
        MOD.build_register(self.root)
        self.assertEqual(tree_digest(self.root), before)


class CliTests(unittest.TestCase):
    def run_cli(self, root, *argv):
        return subprocess.run(
            [sys.executable,
             str(SCRIPTS / "wiki_skill_governance.py"),
             *argv, "--root", str(root)],
            capture_output=True, text=True)

    def test_exit_codes_and_register_artefact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "tools/demo/SKILL.md", LEGAL)
            ok = self.run_cli(root, "check")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            bad = variant("  state: retired", "  state: archived")
            write(root, "tools/demo/SKILL.md", bad)
            res = self.run_cli(root, "check")
            self.assertEqual(res.returncode, 1)
            self.assertIn("unknown-state:archived", res.stdout)
            out = root / "evaluation" / "skill-register.json"
            reg = self.run_cli(root, "register")
            self.assertEqual(reg.returncode, 0, reg.stdout + reg.stderr)
            written = json.loads(out.read_text(encoding="utf-8"))
            # archived state: unknown-state + history-state-mismatch
            self.assertEqual(written["violations_total"], 2)
            self.assertEqual(
                out.read_text(encoding="utf-8"),
                MOD.render_register(MOD.build_register(root)))


if __name__ == "__main__":
    unittest.main()
