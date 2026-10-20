#!/usr/bin/env python3
"""Tests for scripts/wiki_treatment.py — citation treatment
signals (consolidated queue item 10, 2030-10-20).

The register proves standing the way a citator does: later
treatment is recorded as append-only events, a subject's
standing grade is its STRONGEST signal (the most negative
treatment governs), and pages resting on a fallen page are
weakened transitively — computed over the batch-3.1 typed
`grounds` edges, never written back.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def load_treatment_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_treatment_under_test", SCRIPTS / "wiki_treatment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wt = load_treatment_module()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(body, extra_fm=""):
    return ("---\ntitle: Fixture\ntype: source\n"
            "created: 2030-10-20\nupdated: 2030-10-20\n"
            "sources:\n  - raw/sources/fixture.md\n"
            "tags: [fixture]\n"
            f"{extra_fm}"
            "---\n\n# Fixture\n\n"
            f"{body}\n")


def _event(eid, page, claim, grade):
    return {"kind": "treatment", "id": eid,
            "date": "2030-10-20", "recorded": "2030-10-20",
            "subject": {"page": page, "claim": claim},
            "grade": grade,
            "treated_by": {"source": "test", "detail": ""},
            "reason": "fixture"}


class StandingFoldTests(unittest.TestCase):

    def test_strongest_signal_governs(self):
        events = [_event("treat-0001", "wiki/a.md", None, "followed"),
                  _event("treat-0002", "wiki/a.md", None, "negative"),
                  _event("treat-0003", "wiki/a.md", None, "followed")]
        standings = wt.subject_standings(events)
        self.assertEqual(
            standings[("wiki/a.md", None)]["grade"], "negative")
        self.assertEqual(
            standings[("wiki/a.md", None)]["events"],
            ["treat-0001", "treat-0002", "treat-0003"])

    def test_claim_scope_is_a_separate_subject(self):
        events = [_event("treat-0001", "wiki/a.md", "claim x",
                         "negative"),
                  _event("treat-0002", "wiki/a.md", None, "followed")]
        pages = wt.page_standings(events)
        # The page folds to its worst-treated claim, and the
        # breakdown keeps the scopes apart.
        self.assertEqual(pages["wiki/a.md"]["grade"], "negative")
        self.assertEqual(pages["wiki/a.md"]["claims"],
                         {"claim x": "negative"})

    def test_invalid_grade_is_ignored_by_the_fold(self):
        events = [_event("treat-0001", "wiki/a.md", None, "bogus"),
                  _event("treat-0002", "wiki/a.md", None, "caution")]
        standings = wt.subject_standings(events)
        self.assertEqual(
            standings[("wiki/a.md", None)]["grade"], "caution")


class RecordTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write(self.root / "wiki/sources/page-a.md",
               _page("Body."))
        self.register = self.root / "evaluation" / "reg.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_appends_with_sequential_ids(self):
        e1 = wt.record_event(
            "wiki/sources/page-a.md", None, "followed",
            "2030-10-20", "wiki/log.md", "", "first",
            register_path=self.register, root=self.root)
        e2 = wt.record_event(
            "wiki/sources/page-a.md", "one claim", "caution",
            "2030-10-20", "wiki/log.md", "", "second",
            register_path=self.register, root=self.root)
        self.assertEqual((e1["id"], e2["id"]),
                         ("treat-0001", "treat-0002"))
        _header, events = wt.read_register(self.register)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["subject"]["claim"], "one claim")

    def test_record_rejects_bad_grade(self):
        with self.assertRaises(ValueError):
            wt.record_event(
                "wiki/sources/page-a.md", None, "shaky",
                "2030-10-20", "wiki/log.md", "", "nope",
                register_path=self.register, root=self.root)

    def test_record_rejects_missing_page(self):
        with self.assertRaises(ValueError):
            wt.record_event(
                "wiki/sources/nope.md", None, "followed",
                "2030-10-20", "wiki/log.md", "", "nope",
                register_path=self.register, root=self.root)

    def test_record_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            wt.record_event(
                "wiki/sources/page-a.md", None, "followed",
                "20 Oct 2030", "wiki/log.md", "", "nope",
                register_path=self.register, root=self.root)


class WeakeningFixtureTests(unittest.TestCase):
    """Transitive weakening over a fixture tree:

      page-a --grounds--> page-b --grounds--> page-c (negative)
      page-d --mentions-> page-c            (not weakened)
      page-e   superseded (superseded_by frontmatter)
      page-f --grounds--> page-e            (weakened via page-e)
      page-g --grounds--> page-f            (weakened, distance 2)
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.root = root
        _write(root / "wiki/sources/page-c.md",
               _page("The fallen claim lives here."))
        _write(root / "wiki/sources/page-b.md", _page(
            "## Evidence\n\nRests on [[page-c]]."))
        _write(root / "wiki/sources/page-a.md", _page(
            "## Sources\n\nRests on [[page-b]]."))
        _write(root / "wiki/sources/page-d.md", _page(
            "## Discussion\n\nMentions [[page-c]] in passing."))
        _write(root / "wiki/sources/page-e.md", _page(
            "Replaced.", extra_fm="superseded_by: page-a\n"))
        _write(root / "wiki/sources/page-f.md", _page(
            "## Basis\n\nRests on [[page-e]]."))
        _write(root / "wiki/sources/page-g.md", _page(
            "## Evidence\n\nRests on [[page-f]]."))
        _write(root / "wiki/filings/page-h.md", _page(
            "## Evidence\n\nFilings are excluded: [[page-c]]."))
        cls.register = root / "evaluation" / "treatment.jsonl"
        wt.record_event(
            "wiki/sources/page-c.md", None, "negative",
            "2030-10-20", "wiki/log.md", "", "fixture fall",
            register_path=cls.register, root=root)
        cls.result = wt.weakened_pages(root, cls.register)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _row(self, page):
        for row in self.result["weakened"]:
            if row["page"] == page:
                return row
        return None

    def test_fallen_set(self):
        fallen = {r["page"] for r in self.result["fallen"]}
        self.assertEqual(fallen, {"wiki/sources/page-c.md",
                                  "wiki/sources/page-e.md"})
        bases = {r["page"]: r["basis"]
                 for r in self.result["fallen"]}
        self.assertEqual(bases["wiki/sources/page-c.md"][0]["kind"],
                         "treatment")
        self.assertEqual(bases["wiki/sources/page-e.md"][0]["kind"],
                         "superseded")

    def test_direct_dependent_weakened_at_distance_1(self):
        row = self._row("wiki/sources/page-b.md")
        self.assertIsNotNone(row)
        self.assertEqual(row["distance"], 1)
        self.assertEqual(row["weakened_by"],
                         [{"page": "wiki/sources/page-c.md",
                           "distance": 1}])

    def test_transitive_dependent_weakened_at_distance_2(self):
        row = self._row("wiki/sources/page-a.md")
        self.assertIsNotNone(row)
        self.assertEqual(row["distance"], 2)
        row_g = self._row("wiki/sources/page-g.md")
        self.assertIsNotNone(row_g)
        self.assertEqual(row_g["distance"], 2)
        self.assertEqual(row_g["weakened_by"],
                         [{"page": "wiki/sources/page-e.md",
                           "distance": 2}])

    def test_mention_only_dependent_not_weakened(self):
        self.assertIsNone(self._row("wiki/sources/page-d.md"))

    def test_fallen_pages_not_listed_as_weakened(self):
        weakened = {r["page"] for r in self.result["weakened"]}
        self.assertNotIn("wiki/sources/page-c.md", weakened)
        self.assertNotIn("wiki/sources/page-e.md", weakened)

    def test_filings_excluded_from_the_graph(self):
        self.assertIsNone(self._row("wiki/filings/page-h.md"))

    def test_report_counts(self):
        report = wt.treatment_report(self.root, self.register)
        self.assertEqual(report["events"], 1)
        self.assertEqual(report["subjects_by_grade"]["negative"], 1)
        self.assertEqual(report["weakened_count"],
                         len(self.result["weakened"]))
        self.assertGreaterEqual(report["grounds_edges"], 4)


if __name__ == "__main__":
    unittest.main()
