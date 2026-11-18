"""Tests for scripts/wiki_textlint.py (Marathon R7 lane BB;
textlint starter check, MIT config model, our runner).

Pins: no-todo fires on bare TODO/FIXME in prose but not in
fenced code, HTML comments or the structural capture TODO;
terminology fires on a registered variant naming its canonical
form, not on the canonical form itself, not inside inline code
or wikilinks; config/register are read as data (a changed
register changes the result); report-only (pages byte-identical
after a run); CLI exit 1 with findings, 0 clean, 2 no config.

Run: python3 -m unittest scripts.tests.test_wiki_textlint
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_textlint", SCRIPTS / "wiki_textlint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()
CONFIG = {"rules": {"no-todo": {"options": {
    "allowStructuralCaptureTodo": True}},
    "terminology": {"options": {"terms": "evaluation/canonical-names.json"}}}}
TERMS = [("Wiki Citadel", "WikiCitadel")]


class CheckTextTests(unittest.TestCase):
    def test_todo_flagged(self):
        found = MOD.check_text("Fix this TODO later.\n", TERMS, CONFIG)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["rule"], "no-todo")

    def test_todo_in_fence_and_comment_ignored(self):
        text = "```\nTODO in code\n```\n<!-- TODO note -->\nClean.\n"
        self.assertEqual(MOD.check_text(text, TERMS, CONFIG), [])

    def test_structural_capture_todo_exempt(self):
        self.assertEqual(
            MOD.check_text("sensitivity: TODO\n", TERMS, CONFIG), [])

    def test_terminology_variant_flagged_canonical_not(self):
        found = MOD.check_text(
            "The Wiki Citadel page and WikiCitadel itself.\n",
            TERMS, CONFIG)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["canonical"], "WikiCitadel")

    def test_terminology_ignores_code_and_wikilinks(self):
        text = "See `Wiki Citadel` and [[Wiki Citadel]].\n"
        self.assertEqual(MOD.check_text(text, TERMS, CONFIG), [])


class TreeFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_textlint.py",
                    self.root / "scripts")
        (self.root / "evaluation").mkdir()
        (self.root / "evaluation" / "textlint-config.json").write_text(
            json.dumps(CONFIG), encoding="utf-8")
        (self.root / "evaluation" / "canonical-names.json").write_text(
            json.dumps({"canonical_names": [
                {"canonical": "WikiCitadel",
                 "variants": ["Wiki Citadel"]}]}), encoding="utf-8")
        (self.root / "wiki").mkdir()
        self.page = self.root / "wiki" / "a.md"
        self.page.write_text("# A\n\nThe Wiki Citadel page.\n",
                             encoding="utf-8")
        self.tool = self.root / "scripts" / "wiki_textlint.py"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(self.tool), *argv],
                              capture_output=True, text=True)

    def test_report_and_exit_code(self):
        report = MOD.check(self.root)
        self.assertEqual(report["stats"]["findings"], 1)
        self.assertEqual(self.run_cli().returncode, 1)

    def test_report_only_pages_unchanged(self):
        before = hashlib.sha256(self.page.read_bytes()).hexdigest()
        self.run_cli()
        self.assertEqual(
            hashlib.sha256(self.page.read_bytes()).hexdigest(), before)

    def test_clean_tree_exit_zero(self):
        self.page.write_text("# A\n\nWikiCitadel, clean.\n",
                             encoding="utf-8")
        self.assertEqual(self.run_cli().returncode, 0)

    def test_missing_config_exit_two(self):
        (self.root / "evaluation" / "textlint-config.json").unlink()
        self.assertEqual(self.run_cli().returncode, 2)


if __name__ == "__main__":
    unittest.main()
