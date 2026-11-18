"""Tests for the Lens Ask abstention contract (batch 2.1).

Covers ``tools/ask/answer_contract.py`` (the deterministic checks)
and the enforcement wired into ``pickup.py record-answer`` /
``pickup.py validate``:

- an answer record without citations and without an abstention flag
  FAILS validation;
- a cited answer passes; an abstention (flag + reason) passes;
- each sub-answer of a decomposed answer is held to the same rule,
  and the composed citations must cover the sub-answers' citations;
- citations must resolve to real wiki pages when a wiki root is
  given (checked against a temporary wiki tree, plus the real repo
  for the shipped fixtures).

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_answer_contract -v
or directly:
    python3 tools/ask/tests/test_answer_contract.py

No network is used.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import answer_contract  # noqa: E402
import pickup  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_wiki(tmp: str) -> Path:
    """A tiny wiki tree: wiki/overview.md, wiki/syntheses/decisions.md."""
    wiki = Path(tmp) / "wiki"
    (wiki / "syntheses").mkdir(parents=True)
    (wiki / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (wiki / "syntheses" / "decisions.md").write_text(
        "# Decisions\n", encoding="utf-8"
    )
    return wiki


def cited_payload():
    return {
        "question_type": "factual",
        "answer": "Azure is the canonical home.",
        "citations": ["overview"],
    }


class ValidateAnswerTests(unittest.TestCase):
    def test_cited_answer_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            self.assertEqual(
                answer_contract.validate_answer(cited_payload(), wiki), []
            )

    def test_no_citations_no_abstention_fails(self):
        payload = {"answer": "An answer with nothing behind it."}
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(errors)
        self.assertTrue(any("abstention contract" in e for e in errors))

    def test_empty_citations_no_abstention_fails(self):
        payload = {"answer": "Still nothing behind it.", "citations": []}
        self.assertTrue(answer_contract.validate_answer(payload))

    def test_abstention_passes_without_citations(self):
        payload = {
            "answer": "The wiki does not record this.",
            "abstention_reason": "No page records the lease date.",
        }
        self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_abstention_flag_without_reason_fails(self):
        record = {
            "answer": "The wiki does not record this.",
            "citations": [],
            "abstained": True,
        }
        self.assertTrue(answer_contract.validate_answer(record))

    def test_stored_abstention_record_passes(self):
        record = {
            "answer": "The wiki does not record this.",
            "citations": [],
            "abstained": True,
            "abstention_reason": "No page records the lease date.",
        }
        self.assertEqual(answer_contract.validate_answer(record), [])

    def test_missing_answer_text_fails(self):
        payload = {"citations": ["overview"]}
        self.assertTrue(answer_contract.validate_answer(payload))

    def test_unknown_question_type_fails(self):
        payload = cited_payload()
        payload["question_type"] = "riddle"
        self.assertTrue(answer_contract.validate_answer(payload))

    def test_all_question_types_pass(self):
        for qtype in answer_contract.QUESTION_TYPES:
            payload = cited_payload()
            payload["question_type"] = qtype
            self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_unresolvable_citation_fails_with_wiki_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            payload = cited_payload()
            payload["citations"] = ["no-such-page"]
            errors = answer_contract.validate_answer(payload, wiki)
            self.assertTrue(any("does not resolve" in e for e in errors))

    def test_bare_stem_citation_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            payload = cited_payload()
            payload["citations"] = ["decisions"]  # syntheses/decisions.md
            self.assertEqual(
                answer_contract.validate_answer(payload, wiki), []
            )

    def test_citation_not_checked_without_wiki_root(self):
        payload = cited_payload()
        payload["citations"] = ["any-page-id"]
        self.assertEqual(answer_contract.validate_answer(payload), [])


class DecompositionTests(unittest.TestCase):
    def decomposed_payload(self):
        return {
            "answer": "Part one is cited; part two is abstained.",
            "citations": ["overview"],
            "sub_answers": [
                {
                    "question": "Part one?",
                    "answer": "Cited answer.",
                    "citations": ["overview"],
                },
                {
                    "question": "Part two?",
                    "answer": "The wiki does not record this.",
                    "abstention_reason": "No page covers part two.",
                },
            ],
        }

    def test_decomposed_answer_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            self.assertEqual(
                answer_contract.validate_answer(
                    self.decomposed_payload(), wiki
                ),
                [],
            )

    def test_uncited_unabstained_sub_answer_fails(self):
        payload = self.decomposed_payload()
        payload["sub_answers"][0] = {
            "question": "Part one?",
            "answer": "Asserted with nothing behind it.",
        }
        self.assertTrue(answer_contract.validate_answer(payload))

    def test_composed_citations_must_cover_sub_citations(self):
        payload = self.decomposed_payload()
        payload["citations"] = []
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(any("omit sub-answer" in e for e in errors))


class RecordBuildingTests(unittest.TestCase):
    def entry(self):
        return {
            "id": "q_fixture0009",
            "question": "A question?",
            "asker": "owner@example.invalid",
            "asked_at": "2026-10-20T12:00:00Z",
            "status": "pending",
        }

    def test_abstention_fields_recorded(self):
        record = pickup.build_qa_record(
            self.entry(),
            "The wiki does not record this.",
            [],
            "2026-10-20T12:05:00Z",
            question_type="factual",
            abstention_reason="No page records it.",
        )
        self.assertTrue(record["abstained"])
        self.assertEqual(record["abstention_reason"], "No page records it.")
        self.assertEqual(record["question_type"], "factual")
        self.assertEqual(record["status"], "answered")
        self.assertEqual(answer_contract.validate_answer(record), [])

    def test_sub_answers_recorded(self):
        record = pickup.build_qa_record(
            self.entry(),
            "Composed answer.",
            ["overview"],
            "2026-10-20T12:05:00Z",
            sub_answers=[
                {
                    "question": "Part?",
                    "answer": "Sub answer.",
                    "citations": ["overview"],
                },
                {
                    "question": "Other part?",
                    "answer": "Not recorded.",
                    "abstention_reason": "Missing.",
                },
            ],
        )
        subs = record["sub_answers"]
        self.assertEqual(subs[0]["citations"], ["overview"])
        self.assertNotIn("abstained", subs[0])
        self.assertTrue(subs[1]["abstained"])
        self.assertEqual(subs[1]["abstention_reason"], "Missing.")

    def test_proposal_markdown_shows_abstention_and_sub_answers(self):
        record = pickup.build_qa_record(
            self.entry(),
            "The wiki does not record this.",
            [],
            "2026-10-20T12:05:00Z",
            abstention_reason="No page records it.",
        )
        markdown = pickup.stage_proposal_markdown(record)
        self.assertIn("## Abstention", markdown)
        self.assertIn("No page records it.", markdown)


class RecordAnswerCliTests(unittest.TestCase):
    def run_cli(self, tmp_path, payload):
        answer_file = tmp_path / "answer.json"
        answer_file.write_text(json.dumps(payload), encoding="utf-8")
        qa_file = tmp_path / "wiki" / "access" / "qa-2026.jsonl"
        staging_dir = tmp_path / "staging" / "proposed"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            rc = pickup.main(
                [
                    "--qa-file", str(qa_file),
                    "--staging-dir", str(staging_dir),
                    "record-answer",
                    "--answer-file", str(answer_file),
                ]
            )
        return rc, qa_file, staging_dir, stderr.getvalue()

    def test_uncited_unabstained_answer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "question_entry": {
                    "id": "q_fixture0010",
                    "question": "Anything?",
                    "asker": "owner@example.invalid",
                    "asked_at": "2026-10-20T12:00:00Z",
                    "status": "pending",
                },
                "answer": "Invented, with nothing behind it.",
                "citations": [],
            }
            rc, qa_file, staging_dir, stderr = self.run_cli(tmp_path, payload)
            self.assertEqual(rc, 1)
            self.assertIn("refused", stderr)
            # Nothing was appended and no proposal was written.
            self.assertEqual(pickup.read_records(qa_file), [])
            self.assertFalse(
                (staging_dir / "qa-q_fixture0010.md").exists()
            )

    def test_abstention_fixture_records_end_to_end(self):
        fixture = FIXTURES / "sample_abstention.json"
        self.assertTrue(fixture.exists())
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            qa_file = tmp_path / "wiki" / "access" / "qa-2026.jsonl"
            staging_dir = tmp_path / "staging" / "proposed"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = pickup.main(
                    [
                        "--qa-file", str(qa_file),
                        "--staging-dir", str(staging_dir),
                        "record-answer",
                        "--answer-file", str(fixture),
                    ]
                )
            self.assertEqual(rc, 0)
            records = pickup.read_records(qa_file)
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertTrue(record["abstained"])
            self.assertIn("lease", record["abstention_reason"])
            self.assertEqual(record["citations"], [])
            proposal = staging_dir / "qa-q_fixture0003.md"
            self.assertTrue(proposal.exists())
            self.assertIn(
                "## Abstention", proposal.read_text(encoding="utf-8")
            )


class ValidateCliTests(unittest.TestCase):
    def test_validate_flags_a_bad_stored_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            qa_file = Path(tmp) / "qa-2026.jsonl"
            good = {
                "id": "q_good",
                "answer": "Cited.",
                "citations": ["overview"],
                "status": "answered",
            }
            bad = {
                "id": "q_bad",
                "answer": "Uncited and unabstained.",
                "citations": [],
                "status": "answered",
            }
            pickup.append_record(qa_file, good)
            pickup.append_record(qa_file, bad)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = pickup.main(
                    ["--qa-file", str(qa_file), "validate"]
                )
            self.assertEqual(rc, 1)
            out = stdout.getvalue()
            self.assertIn("q_good: ok", out)
            self.assertIn("q_bad: FAIL", out)


def make_rich_wiki(tmp: str) -> Path:
    """A wiki whose pages carry known passage text.

    wiki/overview.md states a fact in a wrapped sentence;
    wiki/syntheses/decisions.md carries an open contradiction
    callout; wiki/syntheses/plain.md is unremarkable.
    """
    wiki = Path(tmp) / "wiki"
    (wiki / "syntheses").mkdir(parents=True)
    (wiki / "overview.md").write_text(
        "# Overview\n\nAzure is the canonical home of this wiki,\n"
        "and integrations are pushed there.\n",
        encoding="utf-8",
    )
    (wiki / "syntheses" / "decisions.md").write_text(
        "# Decisions\n\n> [!warning] Contradiction — two sources "
        "disagree on the date.\n\nThe decision stands.\n",
        encoding="utf-8",
    )
    (wiki / "syntheses" / "plain.md").write_text(
        "# Plain\n\nA quiet page with nothing flagged.\n",
        encoding="utf-8",
    )
    return wiki


PASSAGE = "Azure is the canonical home of this wiki, and integrations are pushed there."


def rich_answer(**overrides):
    payload = {
        "answer": "Azure is the canonical home.",
        "citations": ["overview"],
        "citation_details": [
            {"page": "overview", "score": 0.9, "passage": PASSAGE}
        ],
    }
    payload.update(overrides)
    return payload


class RichCitationTests(unittest.TestCase):
    def test_scored_citation_with_verbatim_passage_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            self.assertEqual(
                answer_contract.validate_answer(rich_answer(), wiki), []
            )

    def test_passage_matching_normalises_whitespace_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            payload = rich_answer(citation_details=[{
                "page": "overview", "score": 0.9,
                "passage": "Azure is the canonical   home of this wiki,\nand integrations are pushed there.",
            }])
            self.assertEqual(
                answer_contract.validate_answer(payload, wiki), []
            )

    def test_score_out_of_range_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            for bad in (-0.1, 1.5, "high"):
                payload = rich_answer(citation_details=[{
                    "page": "overview", "score": bad, "passage": PASSAGE,
                }])
                errors = answer_contract.validate_answer(payload, wiki)
                self.assertTrue(errors, "score %r should fail" % (bad,))

    def test_rich_citation_needs_both_score_and_passage(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            for detail in ({"page": "overview", "score": 0.9},
                           {"page": "overview", "passage": PASSAGE}):
                payload = rich_answer(citation_details=[detail])
                errors = answer_contract.validate_answer(payload, wiki)
                self.assertTrue(errors, "%r should fail" % (detail,))

    def test_passage_not_in_page_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            payload = rich_answer(citation_details=[{
                "page": "overview", "score": 0.9,
                "passage": "GitHub is the canonical home of this wiki.",
            }])
            errors = answer_contract.validate_answer(payload, wiki)
            self.assertTrue(any("not contained" in e for e in errors))

    def test_inline_rich_citation_in_citations_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            payload = {
                "answer": "Azure is the canonical home.",
                "citations": [
                    {"page": "overview", "score": 0.9, "passage": PASSAGE}
                ],
            }
            self.assertEqual(
                answer_contract.validate_answer(payload, wiki), []
            )

    def test_detail_for_uncited_page_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            payload = rich_answer(citation_details=[
                {"page": "overview", "score": 0.9, "passage": PASSAGE},
                {"page": "syntheses/plain", "score": 0.8,
                 "passage": "A quiet page with nothing flagged."},
            ])
            errors = answer_contract.validate_answer(payload, wiki)
            self.assertTrue(any("not among the citations" in e
                                for e in errors))

    def test_legacy_plain_citations_still_validate(self):
        # Grandfathering: records with plain string citations and no
        # scores, mode or verdict validate exactly as before.
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            legacy = {
                "id": "q_old", "answer": "Azure is the canonical home.",
                "citations": ["overview"], "status": "answered",
            }
            self.assertEqual(
                answer_contract.validate_answer(legacy, wiki), []
            )

    def test_shipped_scored_fixture_validates_against_real_wiki(self):
        fixture = FIXTURES / "sample_scored_answer.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        repo_wiki = Path(__file__).resolve().parents[3] / "wiki"
        self.assertEqual(
            answer_contract.validate_answer(payload, repo_wiki), []
        )


class ModeRuleTests(unittest.TestCase):
    def test_bad_mode_fails(self):
        errors = answer_contract.validate_answer(
            rich_answer(mode="yolo")
        )
        self.assertTrue(any("mode" in e for e in errors))

    def test_search_mode_needs_a_passage(self):
        payload = {
            "answer": "Passages only — Search mode.",
            "citations": ["overview"],
            "mode": "search",
        }
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(any("search mode" in e for e in errors))
        self.assertEqual(
            answer_contract.validate_answer(
                rich_answer(mode="search")), []
        )

    def test_search_mode_abstention_needs_no_passage(self):
        payload = {
            "answer": "The wiki does not record this.",
            "abstention_reason": "no page covers the topic",
            "mode": "search",
        }
        self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_deep_research_needs_two_sub_answers(self):
        payload = rich_answer(mode="deep-research")
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(any("deep-research" in e for e in errors))

        payload["sub_answers"] = [
            {"question": "Part one?", "answer": "One.",
             "citations": ["overview"]},
            {"question": "Part two?", "answer": "Two.",
             "citations": ["overview"]},
        ]
        self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_deep_research_abstention_needs_no_sub_answers(self):
        payload = {
            "answer": "The wiki does not record this.",
            "abstention_reason": "nothing on the topic",
            "mode": "deep-research",
        }
        self.assertEqual(answer_contract.validate_answer(payload), [])


class TrustVerdictTests(unittest.TestCase):
    def verdict(self, payload, wiki=None):
        return answer_contract.compute_trust_verdict(payload, wiki)

    def test_abstention_is_hold(self):
        payload = {
            "answer": "The wiki does not record this.",
            "abstention_reason": "missing",
        }
        self.assertEqual(self.verdict(payload), "hold")

    def test_uncited_claim_is_hold(self):
        self.assertEqual(
            self.verdict({"answer": "A claim.", "citations": []}),
            "hold",
        )

    def test_plain_cited_answer_is_ok(self):
        payload = {"answer": "A.", "citations": ["overview"]}
        self.assertEqual(self.verdict(payload), "ok")

    def test_mean_score_boundary(self):
        at = rich_answer(citation_details=[
            {"page": "overview", "score": 0.5, "passage": PASSAGE}])
        self.assertEqual(self.verdict(at), "ok")
        below = rich_answer(citation_details=[
            {"page": "overview", "score": 0.49, "passage": PASSAGE}])
        self.assertEqual(self.verdict(below), "hold")

    def test_weak_single_score_boundary(self):
        # Spread kept under CONFLICT_SPREAD so only the floor rule
        # decides: a score of exactly WEAK_SCORE_FLOOR is not weak.
        at = rich_answer(citation_details=[
            {"page": "overview", "score": 0.25, "passage": PASSAGE},
            {"page": "syntheses/plain", "score": 0.8, "passage": "x"},
        ], citations=["overview", "syntheses/plain"])
        self.assertEqual(self.verdict(at), "ok")
        below = rich_answer(citation_details=[
            {"page": "overview", "score": 0.24, "passage": PASSAGE},
            {"page": "syntheses/plain", "score": 0.8, "passage": "x"},
        ], citations=["overview", "syntheses/plain"])
        self.assertEqual(self.verdict(below), "hold")

    def test_conflicting_scores_in_one_unit_is_review(self):
        payload = rich_answer(
            citations=["overview", "syntheses/plain"],
            citation_details=[
                {"page": "overview", "score": 0.95, "passage": PASSAGE},
                {"page": "syntheses/plain", "score": 0.35,
                 "passage": "A quiet page with nothing flagged."},
            ])
        self.assertEqual(self.verdict(payload), "review")

    def test_wide_spread_with_strong_low_end_is_not_review(self):
        payload = rich_answer(
            citations=["overview", "syntheses/plain"],
            citation_details=[
                {"page": "overview", "score": 1.0, "passage": PASSAGE},
                {"page": "syntheses/plain", "score": 0.40,
                 "passage": "A quiet page with nothing flagged."},
            ])
        self.assertEqual(self.verdict(payload), "ok")

    def test_contradiction_callout_page_is_review_with_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_rich_wiki(tmp)
            payload = {
                "answer": "The decision stands.",
                "citations": ["syntheses/decisions"],
            }
            self.assertEqual(self.verdict(payload), "ok")
            self.assertEqual(self.verdict(payload, wiki), "review")

    def test_stored_verdict_must_agree_with_computed(self):
        payload = rich_answer(trust_verdict="hold")
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(any("trust_verdict" in e for e in errors))
        payload = rich_answer(trust_verdict="ok")
        self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_stored_review_over_structural_ok_is_accepted(self):
        # The contradiction-callout overlay can raise ok -> review;
        # validation without page text must not call that a mismatch.
        payload = {
            "answer": "The decision stands.",
            "citations": ["syntheses/decisions"],
            "trust_verdict": "review",
        }
        self.assertEqual(answer_contract.validate_answer(payload), [])

    def test_bad_verdict_value_fails(self):
        payload = rich_answer(trust_verdict="great")
        errors = answer_contract.validate_answer(payload)
        self.assertTrue(any("trust_verdict" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
