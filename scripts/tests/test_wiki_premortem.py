#!/usr/bin/env python3
"""Tests for the premortem machinery (consolidated-queue
item 36):

  - scripts/wiki_decision_gate.py: has_written_premortem
    tells a written block from the generator placeholder
    and from no block at all; premortem_status scans only
    prop-*.md in staging/proposed/;
  - the live tree: the four proposals item 36(b) named
    (prop-5cd495b8, prop-b897a630, prop-474389db,
    prop-9f662837) carry written premortems;
  - scripts/wiki_refine.py + scripts/wiki_evolve.py: newly
    staged proposals end with the placeholder block
    (explicit NOT YET WRITTEN marker), never with reasons a
    generator invented;
  - scripts/wiki_eval_extended.py: predict_preflight
    returns the open prediction ids for the run's subject
    key, and a warning (never an exception) when none is
    registered.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load("wiki_decision_gate")

WRITTEN = """# Page

Body.

---

## Premortem (2030-10-20)

It is 2027-04-20 and this failed. The reasons were:

1. **It broke.** — Mitigation: a guard.
"""

PLACEHOLDER = """# Page

---

## Premortem (not yet written)

**NOT YET WRITTEN.** Before this proposal is put to the
owner, a separate pass replaces this placeholder.
"""

DATED_BUT_PLACEHOLDER_BODY = """# Page

## Premortem (2030-10-20)

**NOT YET WRITTEN.** Still just the marker, under a dated
heading.
"""


class TestDetection(unittest.TestCase):
    def test_written_block_counts(self):
        self.assertTrue(gate.has_written_premortem(WRITTEN))

    def test_no_block_does_not_count(self):
        self.assertFalse(gate.has_written_premortem("# Page\n"))

    def test_placeholder_does_not_count(self):
        self.assertFalse(gate.has_written_premortem(PLACEHOLDER))

    def test_dated_heading_with_placeholder_body_does_not_count(self):
        self.assertFalse(
            gate.has_written_premortem(DATED_BUT_PLACEHOLDER_BODY))

    def test_marker_in_a_later_section_does_not_spoil(self):
        text = (WRITTEN + "\n## Notes\n\nThe marker NOT YET "
                "WRITTEN is discussed here as text.\n")
        self.assertTrue(gate.has_written_premortem(text))

    def test_status_scans_only_proposals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdir = root / "staging" / "proposed"
            pdir.mkdir(parents=True)
            (pdir / "prop-aaa.md").write_text(WRITTEN,
                                              encoding="utf-8")
            (pdir / "prop-bbb.md").write_text(PLACEHOLDER,
                                              encoding="utf-8")
            (pdir / "qa-q_1.md").write_text("# qa\n",
                                            encoding="utf-8")
            self.assertEqual(gate.premortem_status(root),
                             [("prop-aaa", True),
                              ("prop-bbb", False)])


class TestGenerators(unittest.TestCase):
    def test_refine_staged_content_ends_with_placeholder(self):
        refine = _load("wiki_refine")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "wiki" / "overview.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Overview\n\nBody.\n",
                              encoding="utf-8")
            content = refine.proposal_page_content(root, {
                "target_path": "wiki/overview.md",
                "section": "Refinement proposal",
                "label": "HIGH", "kind": "stale-citation",
                "id": "refine-stale-citation-deadbeef",
                "sketch": "Re-check it.",
                "evidence": {"question_id": "q_1"},
                "new_page": False,
            })
        self.assertIn("## Premortem (not yet written)", content)
        self.assertIn("NOT YET WRITTEN", content)
        self.assertIn("templates/proposal.md", content)
        # and the gate agrees it is not yet a written premortem
        self.assertFalse(gate.has_written_premortem(content))

    def test_evolve_staged_content_ends_with_placeholder(self):
        evolve = _load("wiki_evolve")

        class StubStore:
            def read_page(self, rel):
                return f"# {rel}\n\nBody.\n"

        content = evolve.proposal_content(
            StubStore(), "wiki/syntheses/decisions-record.md",
            "wiki/sources/expert-branches.md",
            [{"signal": "vocabulary-gap", "detail": "terms"}])
        self.assertIn("Framing review", content)
        self.assertIn("## Premortem (not yet written)", content)
        self.assertFalse(gate.has_written_premortem(content))


class TestPredictPreflight(unittest.TestCase):
    def test_warns_without_register_and_reports_open_ids(self):
        ev = _load("wiki_eval_extended")
        wp = _load("wiki_predict")
        with tempfile.TemporaryDirectory() as td:
            register = Path(td) / "predictions.jsonl"
            ids, warning = ev.predict_preflight(register,
                                                "extended-eval")
            self.assertEqual(ids, [])
            self.assertIsNotNone(warning)
            self.assertIn("WARNING", warning)
            results = Path(td) / "results"
            results.mkdir()
            line = wp.add_prediction(
                "Next extended-eval run", "coverage holds",
                "baseline on file", subject_key="extended-eval",
                on=wp.date(2030, 10, 20), path=register,
                results_dir=results)
            ids, warning = ev.predict_preflight(register,
                                                "extended-eval")
            self.assertEqual(ids, [line["id"]])
            self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
