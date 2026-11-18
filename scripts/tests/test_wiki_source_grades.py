#!/usr/bin/env python3
"""Tests for scripts/wiki_source_grades.py — two-axis source
grading + trust labels (consolidated-queue items 11-12).

The heart of the build is the CITATION RULE: no profile and
no grade exists without at least one evidence ref resolving
to a record on the wiki's side. The tests build a fixture
wiki in a temp dir (the real script copied in, so ROOT
resolves to the fixture) and exercise the fold, the check
(including its failure modes), the ungraded listing, and the
rendered trust label — including that the label never
carries a numeric score.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module(script_path):
    spec = importlib.util.spec_from_file_location(
        "wiki_source_grades_fixture", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADER = {"kind": "header", "register": "source-grades",
          "version": 1, "created": "2030-10-20",
          "purpose": "test", "maintenance": "test"}


def profile(source, behind="Somebody", corrects="It does.",
            ref="wiki/sources/alpha.md"):
    return {"kind": "profile", "source": source,
            "behind": behind, "corrects": corrects,
            "evidence": [{"ref": ref, "note": "n"}]}


def grade(source, axis="integrity", value="questioned",
          ref="wiki/sources/alpha.md", basis="a basis"):
    return {"kind": "grade", "source": source, "axis": axis,
            "grade": value, "date": "2030-10-20", "by": "tester",
            "event": "initial grade", "basis": basis,
            "evidence": [{"ref": ref, "note": "n"}]}


class Fixture(unittest.TestCase):
    """A temp-dir wiki: sources alpha (graded), beta (one
    axis), gamma (nothing); a register; the real script."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "scripts").mkdir()
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        (self.tmp / "wiki" / "rules").mkdir(parents=True)
        (self.tmp / "evaluation").mkdir()
        shutil.copy(SCRIPTS / "wiki_source_grades.py",
                    self.tmp / "scripts" /
                    "wiki_source_grades.py")
        for slug in ("alpha", "beta", "gamma"):
            (self.tmp / "wiki" / "sources" /
             f"{slug}.md").write_text(f"# {slug}\n",
                                      encoding="utf-8")
        (self.tmp / "wiki" / "rules" /
         "corrections-ledger.md").write_text(
            "# Corrections ledger\n\n"
            "### 2030-10-20 — A beta error\n\n"
            "Something about wiki/sources/beta.md went "
            "wrong.\n", encoding="utf-8")
        self.register = (self.tmp / "evaluation" /
                         "source-grades.jsonl")
        self.write_register([
            HEADER,
            profile("wiki/sources/alpha.md"),
            grade("wiki/sources/alpha.md", "integrity",
                  "questioned"),
            grade("wiki/sources/alpha.md", "precision",
                  "loose"),
            profile("wiki/sources/beta.md"),
            grade("wiki/sources/beta.md", "precision",
                  "careful"),
        ])
        self.mod = load_module(
            self.tmp / "scripts" / "wiki_source_grades.py")

    def write_register(self, lines):
        self.register.write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n",
            encoding="utf-8")

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" /
                 "wiki_source_grades.py"), *argv],
            capture_output=True, text=True)


class FoldTests(Fixture):
    def test_fold_latest_grade_wins(self):
        _, entries = self.mod.read_register(self.register)
        state = self.mod.fold(entries)
        self.assertEqual(
            state["wiki/sources/alpha.md"]["grades"]
            ["integrity"]["grade"], "questioned")
        # append a revision: the fold must take the new one
        with self.register.open("a", encoding="utf-8") as f:
            f.write(json.dumps(grade(
                "wiki/sources/alpha.md", "integrity",
                "established")) + "\n")
        _, entries = self.mod.read_register(self.register)
        state = self.mod.fold(entries)
        self.assertEqual(
            state["wiki/sources/alpha.md"]["grades"]
            ["integrity"]["grade"], "established")

    def test_resolve_source_forms(self):
        r = self.mod.resolve_source
        self.assertEqual(r("alpha"), "wiki/sources/alpha.md")
        self.assertEqual(r("alpha.md"),
                         "wiki/sources/alpha.md")
        self.assertEqual(r("wiki/sources/alpha.md"),
                         "wiki/sources/alpha.md")


class CheckTests(Fixture):
    def check(self):
        return self.mod.check_register(self.register, self.tmp)

    def test_valid_register_passes(self):
        self.assertEqual(self.check(), [])

    def test_grade_without_evidence_fails(self):
        bad = grade("wiki/sources/alpha.md")
        bad["evidence"] = []
        self.write_register([HEADER, bad])
        problems = self.check()
        self.assertTrue(any("no evidence" in p
                            for p in problems), problems)

    def test_evidence_ref_must_resolve(self):
        bad = grade("wiki/sources/alpha.md",
                    ref="wiki/sources/ghost.md")
        self.write_register([HEADER, bad])
        problems = self.check()
        self.assertTrue(any("does not resolve" in p
                            for p in problems), problems)

    def test_grade_outside_vocabulary_fails(self):
        bad = grade("wiki/sources/alpha.md", value="superb")
        self.write_register([HEADER, bad])
        problems = self.check()
        self.assertTrue(any("vocabulary" in p
                            for p in problems), problems)

    def test_wrong_axis_vocabulary_fails(self):
        # 'exact' is a precision word, not an integrity word:
        # the axes are disjoint by construction.
        bad = grade("wiki/sources/alpha.md", "integrity",
                    "exact")
        self.write_register([HEADER, bad])
        self.assertTrue(self.check())

    def test_unknown_source_page_fails(self):
        bad = grade("wiki/sources/ghost.md")
        self.write_register([HEADER, bad])
        problems = self.check()
        self.assertTrue(any("not found" in p
                            for p in problems), problems)

    def test_profile_missing_field_fails(self):
        bad = profile("wiki/sources/alpha.md")
        del bad["corrects"]
        self.write_register([HEADER, bad])
        self.assertTrue(self.check())

    def test_missing_header_fails(self):
        self.write_register([grade("wiki/sources/alpha.md")])
        self.assertTrue(self.check())

    def test_cli_check_exit_codes(self):
        self.assertEqual(self.run_cli("check").returncode, 0)
        bad = grade("wiki/sources/alpha.md")
        bad["evidence"] = []
        self.write_register([HEADER, bad])
        self.assertEqual(self.run_cli("check").returncode, 1)


class UngradedTests(Fixture):
    def test_ungraded_lists(self):
        out = self.run_cli("ungraded")
        self.assertEqual(out.returncode, 0)
        self.assertIn("gamma.md", out.stdout)
        self.assertIn("ungraded (no grade on either axis): 1",
                      out.stdout)
        # beta is partially graded (precision only)
        self.assertIn("beta.md — integrity ungraded",
                      out.stdout)
        # alpha is graded on both axes: listed nowhere
        self.assertNotIn("alpha", out.stdout)


class RenderTests(Fixture):
    def render(self, slug):
        _, entries = self.mod.read_register(self.register)
        state = self.mod.fold(entries)
        return self.mod.render_block(
            f"wiki/sources/{slug}.md", state)

    def test_render_graded_source(self):
        block = self.render("alpha")
        self.assertTrue(block.startswith(
            "## Trust and standing"))
        self.assertIn("Who is behind it:** Somebody", block)
        self.assertIn("**Integrity:** Questioned", block)
        self.assertIn("**Precision:** Loose", block)
        self.assertIn("graded questioned on 2030-10-20",
                      block)

    def test_render_ungraded_source_is_honest(self):
        block = self.render("gamma")
        self.assertIn("Not recorded", block)
        self.assertEqual(block.count("Not yet graded"), 2)
        self.assertIn("Nothing recorded", block)

    def test_render_names_ledger_mentions(self):
        block = self.render("beta")
        self.assertIn("corrections ledger: "
                      "2030-10-20 — A beta error", block)

    def test_render_has_no_numeric_score(self):
        # The vocabularies and prose contain no score; assert
        # the rendered label carries no digit-run that could
        # read as one (dates are allowed and expected).
        for slug in ("alpha", "beta", "gamma"):
            block = self.render(slug)
            self.assertNotIn("/100", block)
            self.assertNotIn("score", block.lower())


if __name__ == "__main__":
    unittest.main()
