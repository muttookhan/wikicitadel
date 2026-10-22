#!/usr/bin/env python3
"""Tests for tools/ask/sentence_scoring.py (W1.4) — the scorer
behind the RAGBench row schema (evaluation/ragbench-row
-schema.json).

Pins: per-sentence verdicts on fixtures with known ground
truth (supported / union-supported / partially-supported /
unsupported / the numeric trap); schema conformance of every
emitted row via the schema's own validator; usefulness
ordering and duplicate novelty collapse; character-exact span
arithmetic; the lexical stand-in's labelling and caps;
determinism (same input -> byte-identical row, tie-breaks by
key, never by input order); and a scorer run over the shipped
Ask fixtures in this directory.

Run: python3 -m unittest discover -s tools/ask/tests -v
     (or: python3 tools/ask/tests/test_sentence_scoring.py)
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1]
ROOT = ASK_DIR.parents[1]
FIXTURES = ASK_DIR / "tests" / "fixtures"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "sentence_scoring", ASK_DIR / "sentence_scoring.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load_module()

LIGHTHOUSE = {
    "key": "harbour/lighthouse", "page": "harbour/lighthouse",
    "passage": "The harbour lighthouse was built in 1901 and "
               "guides ships into the harbour.",
    "score": 0.9, "anchor": None}
FUNDING = {
    "key": "harbour/funding", "page": "harbour/funding",
    "passage": "The lighthouse upkeep is funded by the harbour "
               "board's annual levy on shipping.",
    "score": 0.8, "anchor": None}
PASSAGES = [LIGHTHOUSE, FUNDING]


def scratch_dir():
    """A writable scratch directory. tempfile's default probe
    intermittently fails in tonight's sandbox (EPERM), so fall
    back to a workspace scratch dir — plain writes work."""
    try:
        return Path(tempfile.mkdtemp(prefix="w14-test-")), True
    except Exception:
        base = Path.home() / "workspace" / ".w14tmp"
        base.mkdir(parents=True, exist_ok=True)
        d = base / f"w14-test-{os.getpid()}"
        d.mkdir(exist_ok=True)
        return d, True


def write_with_retry(path, text):
    """Write *text* to *path*, retrying the sandbox's
    intermittent EPERM refusals (observed tonight) a few times
    before letting the error stand."""
    import time
    last = None
    for _ in range(4):
        try:
            path.write_text(text, encoding="utf-8")
            return
        except PermissionError as exc:
            last = exc
            time.sleep(1.0)
    raise last


class VerdictTests(unittest.TestCase):
    def test_supported_single_passage(self):
        r = M.score_sentence(
            "The harbour lighthouse was built in 1901.", PASSAGES)
        self.assertEqual(r["verdict"], "supported")
        self.assertEqual(r["supporting_keys"],
                         ["harbour/lighthouse"])
        self.assertEqual(r["numeric_missing"], [])

    def test_supported_by_union_of_two_passages(self):
        r = M.score_sentence(
            "The lighthouse was built in 1901, and its upkeep "
            "is funded by an annual levy on shipping.", PASSAGES)
        self.assertEqual(r["verdict"], "supported")
        self.assertEqual(set(r["supporting_keys"]),
                         {"harbour/lighthouse", "harbour/funding"})

    def test_unsupported_fabrication_carries_no_keys(self):
        r = M.score_sentence(
            "Martian colonies fund the lighthouse upkeep "
            "entirely.", PASSAGES)
        self.assertEqual(r["verdict"], "unsupported")
        self.assertEqual(r["supporting_keys"], [])
        self.assertEqual(r["selected"], [])

    def test_numeric_trap_is_never_supported(self):
        # Every content word matches; only the year is wrong.
        # A figure no passage states caps the verdict at partial.
        r = M.score_sentence(
            "The harbour lighthouse was built in 1902.", PASSAGES)
        self.assertEqual(r["verdict"], "partially-supported")
        self.assertEqual(r["numeric_missing"], ["1902"])

    def test_partially_supported(self):
        r = M.score_sentence(
            "The lighthouse guides ships and also hosts a "
            "museum cafe.", PASSAGES)
        self.assertEqual(r["verdict"], "partially-supported")
        self.assertEqual(r["supporting_keys"],
                         ["harbour/lighthouse"])

    def test_no_content_sentence(self):
        r = M.score_sentence("It is so.", PASSAGES)
        self.assertEqual(r["verdict"], "unsupported")
        self.assertTrue(r["no_content"])

    def test_citationless_answer_is_unsupported(self):
        rec = {"question": "When was the lighthouse built?",
               "answer": "The harbour lighthouse was built "
                         "in 1901.",
               "citations": ["harbour/lighthouse"]}
        row = M.score_answer_record(rec)
        self.assertEqual(
            row["response_sentences"][0]["support_verdict"],
            "unsupported")


class UsefulnessTests(unittest.TestCase):
    Q = "How is the lighthouse upkeep funded?"

    def test_most_useful_first(self):
        ranked = M.filter_context(self.Q, PASSAGES)
        self.assertEqual(ranked[0]["key"], "harbour/funding")
        self.assertGreater(
            ranked[0]["usefulness"]["question_coverage"],
            ranked[1]["usefulness"]["question_coverage"])

    def test_duplicate_novelty_collapses(self):
        dup = dict(FUNDING, key="harbour/funding-copy")
        ranked = M.filter_context(self.Q,
                                  [FUNDING, LIGHTHOUSE, dup])
        copy_row = [e for e in ranked
                    if e["key"] == "harbour/funding-copy"]
        self.assertEqual(len(copy_row), 1)
        self.assertEqual(copy_row[0]["usefulness"]["novelty"],
                         0.0)

    def test_min_usefulness_drops_off_topic(self):
        off = {"key": "lab/qcd", "page": "lab/qcd",
               "passage": "Quantum chromodynamics lectures run "
                          "on Tuesdays in the physics annex.",
               "score": 0.1, "anchor": None}
        ranked = M.filter_context(self.Q, PASSAGES + [off],
                                  min_usefulness=0.1)
        self.assertNotIn("lab/qcd",
                         [e["key"] for e in ranked])

    def test_inputs_not_mutated(self):
        original = [dict(p) for p in PASSAGES]
        M.filter_context(self.Q, PASSAGES)
        self.assertEqual(PASSAGES, original)


class SpanTests(unittest.TestCase):
    PAGE = ("Intro text. The harbour lighthouse was built in "
            "1901 and guides ships into the harbour. Trailing.")
    PASSAGE = ("The harbour lighthouse was built in 1901 and "
               "guides ships into the harbour.")

    def test_locate_in_page_exact_offsets(self):
        span = M.locate_in_page(self.PAGE, self.PASSAGE)
        self.assertEqual(span, (12, 12 + len(self.PASSAGE)))
        self.assertEqual(self.PAGE[span[0]:span[1]],
                         self.PASSAGE)

    def test_locate_missing_passage(self):
        self.assertIsNone(M.locate_in_page(self.PAGE,
                                           "No such text."))

    def test_support_span_first_to_last_matched_token(self):
        span = M.support_span(
            "The lighthouse was built in 1901.", self.PASSAGE)
        self.assertEqual(
            span, (self.PASSAGE.index("lighthouse"),
                   self.PASSAGE.index("1901") + 4))

    def test_precision_recall_exact_fractions(self):
        out = M.span_precision_recall([("p", 0, 40)],
                                      [("p", 20, 30)])
        self.assertEqual(out["precision"], 0.25)
        self.assertEqual(out["recall"], 1.0)
        self.assertEqual(out["intersection_chars"], 10)

    def test_precision_recall_pages_and_empties(self):
        out = M.span_precision_recall([("a", 0, 10)],
                                      [("b", 0, 10)])
        self.assertEqual((out["precision"], out["recall"]),
                         (0.0, 0.0))
        out = M.span_precision_recall([], [])
        self.assertEqual((out["precision"], out["recall"]),
                         (1.0, 1.0))

    def test_end_to_end_page_coordinates(self):
        d, _ = scratch_dir()
        try:
            wiki = d / "wiki" / "harbour"
            wiki.mkdir(parents=True)
            write_with_retry(wiki / "lighthouse.md",
                             "# Lighthouse\n\n" + self.PAGE
                             + "\n")
            rec = {"id": "SPAN-1", "question": "When?",
                   "answer": "The harbour lighthouse was built "
                             "in 1901.",
                   "citations": [],
                   "citation_details": [
                       {"page": "harbour/lighthouse",
                        "passage": self.PASSAGE, "score": 0.9}]}
            row = M.score_answer_record(rec, wiki_dir=d / "wiki")
            col = row["scorer_columns"]["span-exact/v1"]
            self.assertEqual(col["passages_located"], 1)
            spans = col["predicted_spans"][0]
            self.assertEqual(len(spans), 1)
            page_text = M._normalize(
                (wiki / "lighthouse.md").read_text(
                    encoding="utf-8"))
            got = page_text[spans[0]["start"]:spans[0]["end"]]
            self.assertIn("lighthouse", got)
            self.assertIn("1901", got)
            self.assertNotIn("Intro", got)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class StandInTests(unittest.TestCase):
    def setUp(self):
        self.scorer = M.LexicalEntailmentStandIn()

    def test_identical_text_entails(self):
        self.assertEqual(self.scorer.entailment(
            "The lighthouse was built in 1901.",
            "The lighthouse was built in 1901."), 1.0)

    def test_unstated_figure_caps(self):
        self.assertLessEqual(self.scorer.entailment(
            "The lighthouse was built in 1901.",
            "The lighthouse was built in 1902."), 0.25)

    def test_negation_parity_penalty(self):
        self.assertEqual(self.scorer.entailment(
            "The lighthouse was built in 1901.",
            "The lighthouse was not built in 1901."), 0.3)

    def test_stand_in_is_labelled(self):
        self.assertTrue(self.scorer.is_stand_in)
        rec = {"question": "When was the lighthouse built?",
               "answer": "The harbour lighthouse was built "
                         "in 1901.",
               "citation_details": [
                   {"page": "harbour/lighthouse",
                    "passage": LIGHTHOUSE["passage"],
                    "score": 0.9}]}
        row = M.score_answer_record(rec)
        col = row["scorer_columns"][self.scorer.name]
        self.assertTrue(col["stand_in"])
        self.assertEqual(col["citation_recall"], 1.0)
        self.assertEqual(col["citation_precision"], 1.0)


class DeterminismTests(unittest.TestCase):
    REC = {"id": "DET-1",
           "question": "When was the lighthouse built, and "
                       "how is its upkeep funded?",
           "answer": "The lighthouse was built in 1901, and "
                     "its upkeep is funded by an annual levy "
                     "on shipping.",
           "citation_details": [
               {"page": "harbour/lighthouse",
                "passage": LIGHTHOUSE["passage"], "score": 0.9},
               {"page": "harbour/funding",
                "passage": FUNDING["passage"], "score": 0.8}]}

    def test_same_input_same_row_byte_identical(self):
        a = M.score_answer_record(self.REC)
        b = M.score_answer_record(self.REC)
        self.assertEqual(a, b)
        self.assertEqual(
            json.dumps(a, sort_keys=True),
            json.dumps(b, sort_keys=True))

    def test_tie_break_by_key_not_input_order(self):
        s = "The lighthouse guides ships."
        pb = {"key": "b-page", "page": "b-page",
              "passage": "The lighthouse guides ships into "
                         "the harbour.", "score": 0.5,
              "anchor": None}
        pa = {"key": "a-page", "page": "a-page",
              "passage": "The lighthouse guides ships past "
                         "the rocks.", "score": 0.5,
              "anchor": None}
        r1 = M.score_sentence(s, [pb, pa])
        r2 = M.score_sentence(s, [pa, pb])
        self.assertEqual(r1["supporting_keys"],
                         r2["supporting_keys"])
        self.assertEqual(r1["supporting_keys"], ["a-page"])


class RealFixtureTests(unittest.TestCase):
    def load_fixture(self, name):
        return json.loads((FIXTURES / name).read_text(
            encoding="utf-8"))

    def test_all_shipped_fixtures_validate(self):
        for name in ("sample_answer.json",
                     "sample_scored_answer.json",
                     "sample_chunks_record.json",
                     "sample_abstention.json"):
            row = M.score_answer_record(
                self.load_fixture(name), wiki_dir=ROOT / "wiki")
            self.assertEqual(M.validate_row(row), [],
                             f"{name}: row must conform")

    def test_answer_without_passages_scores_unsupported(self):
        row = M.score_answer_record(
            self.load_fixture("sample_answer.json"),
            wiki_dir=ROOT / "wiki")
        verdicts = [s["support_verdict"]
                    for s in row["response_sentences"]]
        self.assertTrue(verdicts)
        self.assertTrue(all(v == "unsupported" for v in verdicts))
        col = row["scorer_columns"]["span-exact/v1"]
        self.assertEqual(col["passages_located"], 0)

    def test_scored_answer_finds_support_and_locates(self):
        row = M.score_answer_record(
            self.load_fixture("sample_scored_answer.json"),
            wiki_dir=ROOT / "wiki")
        verdicts = {s["support_verdict"]
                    for s in row["response_sentences"]}
        self.assertTrue(verdicts & {"supported",
                                    "partially-supported"})
        col = row["scorer_columns"]["span-exact/v1"]
        self.assertGreaterEqual(col["passages_located"], 1)

    def test_real_fixture_run_is_deterministic(self):
        rec = self.load_fixture("sample_scored_answer.json")
        a = M.score_answer_record(rec, wiki_dir=ROOT / "wiki")
        b = M.score_answer_record(rec, wiki_dir=ROOT / "wiki")
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
