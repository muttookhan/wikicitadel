#!/usr/bin/env python3
"""LIT-RAGBench-format abstention benchmark harness (JP4).

Pins scripts/wiki_lit_ragbench.py: the set file loads (header +
items), the fixture-integrity guard (every chunk passage
verbatim in its cited page — rot is an error, not a score), the
decision rule (best-chunk relevance below tau -> abstain, else
answer from the best chunk), and the scoring split (an answer
counts only when grounded in a positive chunk with its key
facts; Abstention is aggregated as its own category).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = load("wiki_lit_ragbench", "scripts/wiki_lit_ragbench.py")
ws = load("wiki_search", "scripts/wiki_search.py")

PASSAGE = "The Zarnok archive keeps forty two shelves of tide ledgers."


def make_tree(tmp):
    root = Path(tmp)
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "zarnok.md").write_text(
        f"# Zarnok\n\n{PASSAGE}\n", encoding="utf-8")
    return root


def item(**kw):
    base = {"id": "LRB-T1", "category": "Integration",
            "question": "How many shelves of tide ledgers does "
                          "the Zarnok archive keep?",
            "positive_chunk_list": [
                {"page": "wiki/zarnok.md", "passage": PASSAGE}],
            "negative_chunk_list": [],
            "expected": "answer",
            "answer_key_facts": ["forty two"]}
    base.update(kw)
    return base


class TestFixtureIntegrity(unittest.TestCase):
    def test_verbatim_chunk_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            self.assertEqual(bench.check_fixture([item()], root),
                             [])

    def test_rotted_chunk_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            bad = item(positive_chunk_list=[
                {"page": "wiki/zarnok.md",
                 "passage": "The Zarnok archive keeps nine shelves."}])
            errors = bench.check_fixture([bad], root)
            self.assertEqual(len(errors), 1)
            self.assertIn("rotted", errors[0])

    def test_missing_page_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            bad = item(positive_chunk_list=[
                {"page": "wiki/absent.md", "passage": PASSAGE}])
            self.assertEqual(len(bench.check_fixture([bad], root)),
                             1)


class TestDecideAndScore(unittest.TestCase):
    def test_grounded_answer_scores_correct(self):
        row = bench.score_item(item(), bench.DEFAULT_TAU,
                               ws.tokenize)
        self.assertTrue(row["correct"], row)

    def test_distractor_only_item_must_abstain(self):
        abst = item(
            id="LRB-T2", category="Abstention",
            question="What colour is the harbour master's "
                     "ceremonial barge?",
            positive_chunk_list=[],
            negative_chunk_list=[
                {"page": "wiki/zarnok.md", "passage": PASSAGE}],
            expected="abstain", answer_key_facts=[])
        row = bench.score_item(abst, bench.DEFAULT_TAU, ws.tokenize)
        self.assertEqual(row["observed"], "abstain")
        self.assertTrue(row["correct"], row)

    def test_answer_from_distractor_is_wrong(self):
        # The distractor covers the question's terms but is not
        # evidence: grounding in it must NOT score correct.
        tricky = item(
            question="How many shelves of tide ledgers?",
            positive_chunk_list=[],
            negative_chunk_list=[
                {"page": "wiki/zarnok.md", "passage": PASSAGE}],
            expected="abstain", answer_key_facts=[])
        row = bench.score_item(tricky, 0.1, ws.tokenize)
        self.assertFalse(row["correct"], row)


class TestRunAggregates(unittest.TestCase):
    def test_abstention_is_its_own_category(self):
        abst = item(id="LRB-T2", category="Abstention",
                    question="What colour is the harbour "
                             "master's ceremonial barge?",
                    positive_chunk_list=[],
                    negative_chunk_list=[
                        {"page": "wiki/zarnok.md",
                         "passage": PASSAGE}],
                    expected="abstain", answer_key_facts=[])
        report = bench.run([item(), abst], bench.DEFAULT_TAU,
                           ws.tokenize)
        self.assertEqual(report["by_category"]["Abstention"]
                         ["items"], 1)
        self.assertEqual(report["abstention_recall"], 1.0)
        self.assertEqual(report["accuracy"], 1.0)


class TestShippedFixture(unittest.TestCase):
    def test_shipped_fixture_is_verbatim_clean(self):
        header, items = bench.load_set(bench.DEFAULT_SET)
        self.assertIsNotNone(header)
        self.assertGreaterEqual(len(items), 8)
        cats = {i["category"] for i in items}
        self.assertIn("Abstention", cats)
        self.assertEqual(bench.check_fixture(items, ROOT), [])


if __name__ == "__main__":
    unittest.main()
