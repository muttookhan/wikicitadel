#!/usr/bin/env python3
"""Tests for scripts/wiki_claim_match.py — claim matching +
verdict inheritance (consolidated-queue item 14; Squash /
Meedan Check via the wave-4 survey).

The behaviours under test: the settled corpus is assembled
from claim pages, beliefs lines and the decisions register
(including superseded forms); an exact repeat scores 1.0 and
ranks first; a reworded repeat still ranks its settled claim
first, above the noise floor; a genuinely new claim stays
below it; a pick is appended to the matches register and the
tool edits nothing else.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cm = load("wiki_claim_match")

CLAIM_TEXT = ("The wiki's hybrid search beats its BM25 baseline "
              "on the golden set")


def fixture_root() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "wiki/sources").mkdir(parents=True)
    (root / "wiki/syntheses").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    (root / "wiki/sources/search.md").write_text(
        "---\n"
        "title: Search\n"
        "type: source\n"
        f'claim: "{CLAIM_TEXT}"\n'
        "outcome_status: rule\n"
        "---\n\n# Search\n", encoding="utf-8")
    (root / "wiki/syntheses/beliefs.md").write_text(
        "---\ntitle: Beliefs\ntype: synthesis\n---\n\n"
        "- Decisions are always his, presented and taken one "
        "by one.\n", encoding="utf-8")
    register = [
        {"kind": "header", "register": "decisions-register"},
        {"kind": "decision", "id": "ch7-d1",
         "title": "Galen's seat on the agent team",
         "status": "active",
         "current_form": "Galen's seat is OPEN: Galen bot "
                         "collaborates over this wiki under "
                         "the filings rules.",
         "superseded_forms": [
             {"form_id": "ch7-d1-reserved",
              "title": "Galen's seat stays RESERVED",
              "superseded_on": "2030-10-16"}]},
    ]
    (root / "evaluation/decisions-register.jsonl").write_text(
        "\n".join(json.dumps(r) for r in register) + "\n",
        encoding="utf-8")
    return root


class CorpusTests(unittest.TestCase):
    def test_corpus_covers_all_three_sources(self):
        corpus = cm.build_corpus(fixture_root())
        kinds = {e["kind"] for e in corpus}
        self.assertEqual(
            kinds, {"claim-page", "belief", "decision",
                    "decision-superseded-form"})
        claim = next(e for e in corpus if e["kind"] == "claim-page")
        self.assertEqual(claim["status"], "rule")
        sup = next(e for e in corpus
                   if e["kind"] == "decision-superseded-form")
        self.assertIn("superseded", sup["status"])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.corpus = cm.build_corpus(fixture_root())

    def test_exact_repeat_scores_one_and_ranks_first(self):
        results = cm.match(CLAIM_TEXT, self.corpus)
        self.assertEqual(results[0][0], 1.0)
        self.assertEqual(results[0][1]["kind"], "claim-page")

    def test_reworded_repeat_finds_its_settled_claim(self):
        reworded = ("On the golden set, hybrid search outperforms "
                    "the BM25 baseline in this wiki")
        results = cm.match(reworded, self.corpus)
        self.assertEqual(results[0][1]["kind"], "claim-page")
        self.assertGreaterEqual(results[0][0], cm.NOISE_FLOOR)

    def test_genuinely_new_claim_stays_below_the_floor(self):
        new = ("Falcons migrate south across the lake each autumn "
               "before the first frost")
        results = cm.match(new, self.corpus)
        top = results[0][0] if results else 0.0
        self.assertLess(top, cm.NOISE_FLOOR)

    def test_superseded_form_surfaces_as_superseded(self):
        results = cm.match("Galen's seat stays reserved",
                           self.corpus)
        self.assertEqual(results[0][1]["kind"],
                         "decision-superseded-form")
        self.assertIn("superseded", results[0][1]["status"])


class RecordTests(unittest.TestCase):
    def test_pick_is_appended_with_header(self):
        root = fixture_root()
        rec = cm.record_pick(root, "owner", "wiki/sources/search.md",
                             "rule", incoming_text=CLAIM_TEXT,
                             when="2030-10-20")
        lines = (root / "evaluation/claim-matches.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["kind"], "header")
        pick = json.loads(lines[1])
        self.assertEqual(pick["picker"], "owner")
        self.assertEqual(pick["verdict_inherited"], "rule")
        self.assertIn("incoming_sha256", pick)
        self.assertEqual(rec["chosen_claim"],
                         "wiki/sources/search.md")


if __name__ == "__main__":
    unittest.main()
