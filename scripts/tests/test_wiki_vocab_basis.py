"""Tests for scripts/wiki_vocab_basis.py — basis lines beside
governed-vocabulary assignments (Marathon R9 lane BA; Mai
basis-line board item).

Pins: sensitivity assignments render first with a basis line
sourced from the assignment's own basis, falling back to the
class meaning; a tag concept's basis is its scopeNote; a
notice application's basis is the notice's applicability;
an assignment with no basis text anywhere is reported by
check; a label the vocabulary does not hold is reported;
registers absent in a tree are reported absent, never as
clean. Fixture roots are built in temp dirs; shipped-data
tests adapt to whichever registers the tree carries.

Run: python3 -m unittest scripts.tests.test_wiki_vocab_basis
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_vocab_basis", SCRIPTS / "wiki_vocab_basis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()


def fixture_root(tmp):
    root = Path(tmp)
    (root / "evaluation").mkdir(parents=True)
    (root / "wiki").mkdir()
    (root / "evaluation" / "sensitivity.json").write_text(
        json.dumps({
            "classes": [
                {"id": "internal",
                 "meaning": "Working material, nobody else's "
                            "business."},
                {"id": "quiet", "meaning": ""},
            ],
            "assignments": [
                {"path": "raw/sources/a.md", "class": "internal",
                 "basis": "Filed by the owner as working "
                          "material."},
                {"path": "raw/sources/b.md", "class": "internal",
                 "basis": ""},
                {"path": "raw/sources/c.md", "class": "quiet",
                 "basis": ""},
                {"path": "raw/sources/d.md", "class": "ghost",
                 "basis": ""},
            ],
        }), encoding="utf-8")
    (root / "evaluation" / "tag-registry.jsonl").write_text(
        json.dumps({"kind": "concept", "id": "access",
                    "prefLabel": "access", "altLabels": [],
                    "definition": "Access records.",
                    "scopeNote": "For access records only.",
                    "status": "preferred",
                    "usage": {"count": 1,
                              "pages": ["wiki/x.md"]}}) + "\n",
        encoding="utf-8")
    (root / "evaluation" / "notice-vocabulary.json").write_text(
        json.dumps({"notices": [{
            "id": "n1", "title": "N1",
            "applicability": "Mechanical: the page is a "
                             "fixture.",
            "fixed_text": "Fixture notice."}]}),
        encoding="utf-8")
    (root / "evaluation" / "notices.jsonl").write_text(
        json.dumps({"kind": "applied", "page": "wiki/x.md",
                    "notice": "n1", "date": "2026-01-01"})
        + "\n", encoding="utf-8")
    return root


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fixture_root(self._tmp.name)
        self.assignments, self.absent = \
            MOD.collect_assignments(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sensitivity_first_and_basis_sources(self):
        sens = [a for a in self.assignments
                if a["family"] == "sensitivity"]
        self.assertEqual(len(sens), 4)
        self.assertEqual(self.assignments[0]["family"],
                         "sensitivity")
        by_path = {a["subject"]: a for a in sens}
        self.assertEqual(by_path["raw/sources/a.md"]
                         ["basis_source"], "assignment basis")
        fallback = by_path["raw/sources/b.md"]
        self.assertEqual(fallback["basis_source"],
                         "class meaning")
        self.assertIn("Working material", fallback["basis"])

    def test_lacking_basis_reported(self):
        lacking = MOD.lacking_basis(self.assignments)
        subjects = {a["subject"] for a in lacking}
        self.assertIn("raw/sources/c.md", subjects)
        ghost = [a for a in lacking
                 if a["subject"] == "raw/sources/d.md"]
        self.assertEqual(len(ghost), 1)
        self.assertIn("not in the vocabulary",
                      ghost[0]["problem"])

    def test_tag_and_notice_basis(self):
        tags = [a for a in self.assignments
                if a["family"] == "tags"]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["basis"],
                         "For access records only.")
        notices = [a for a in self.assignments
                   if a["family"] == "notices"]
        self.assertEqual(len(notices), 1)
        self.assertIn("fixture", notices[0]["basis"])

    def test_retired_notice_not_rendered(self):
        with open(self.root / "evaluation" / "notices.jsonl",
                  "a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"kind": "retired", "page": "wiki/x.md",
                 "notice": "n1", "date": "2026-02-01"}) + "\n")
        assignments, _abs = MOD.collect_assignments(self.root)
        self.assertEqual([a for a in assignments
                          if a["family"] == "notices"], [])

    def test_render_lines_carry_basis(self):
        lines = MOD.render_lines(self.assignments, self.absent)
        text = "\n".join(lines)
        self.assertIn("basis: [assignment basis]", text)
        self.assertIn("basis: NONE AVAILABLE", text)


class ShippedDataTests(unittest.TestCase):
    def test_shipped_registers(self):
        assignments, absent = MOD.collect_assignments(ROOT)
        # Every tree carries at least the notice vocabulary
        # machinery's inputs or reports the family absent.
        self.assertTrue(assignments or absent)
        if "sensitivity" not in absent:
            sens = [a for a in assignments
                    if a["family"] == "sensitivity"]
            self.assertTrue(sens)
            for a in sens:
                self.assertTrue(
                    a["basis"],
                    f"sensitivity assignment {a['subject']} "
                    f"lacks a basis on the shipped register")


if __name__ == "__main__":
    unittest.main()
