"""Tests for tools/ask/pickup.py — non-network parts only.

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_pickup -v
or directly:
    python3 tools/ask/tests/test_pickup.py

No network is used, and the real service token is never read: the token
test writes its own dummy token into a temporary state dir.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pickup  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AUTHORISATION_REF = "owner-directive-build-the-ask-door"


def sample_entry():
    return {
        "id": "q_fixture0001",
        "question": "What is the wiki's canonical home?",
        "asker": "owner@example.invalid",
        "asked_at": "2026-10-13T12:00:00Z",
        "status": "pending",
    }


class BuildQaRecordTests(unittest.TestCase):
    def test_field_correctness(self):
        record = pickup.build_qa_record(
            sample_entry(),
            "Azure is the canonical home.",
            ["overview", "syntheses/decision-register"],
            "2026-10-13T12:05:00Z",
        )
        self.assertEqual(record["id"], "q_fixture0001")
        self.assertEqual(record["question"], "What is the wiki's canonical home?")
        self.assertEqual(record["asker"], "owner@example.invalid")
        self.assertEqual(record["asked_at"], "2026-10-13T12:00:00Z")
        self.assertEqual(record["answered_at"], "2026-10-13T12:05:00Z")
        self.assertEqual(record["answer"], "Azure is the canonical home.")
        self.assertEqual(
            record["citations"], ["overview", "syntheses/decision-register"]
        )
        self.assertEqual(record["status"], "answered")
        self.assertEqual(
            set(record.keys()),
            {
                "id",
                "question",
                "asker",
                "asked_at",
                "answered_at",
                "answer",
                "citations",
                "status",
            },
        )


class AppendReadTests(unittest.TestCase):
    def test_round_trip_two_records_order_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qa-2026.jsonl"
            first = pickup.build_qa_record(
                sample_entry(), "First answer.", ["overview"],
                "2026-10-13T12:05:00Z",
            )
            second_entry = sample_entry()
            second_entry["id"] = "q_fixture0002"
            second_entry["question"] = "A second question?"
            second = pickup.build_qa_record(
                second_entry, "Second answer.", [],
                "2026-10-13T12:06:00Z",
            )
            pickup.append_record(path, first)
            pickup.append_record(path, second)

            records = pickup.read_records(path)
            self.assertEqual(records, [first, second])
            self.assertEqual(
                [r["id"] for r in records], ["q_fixture0001", "q_fixture0002"]
            )
            # Exactly one JSON object per line.
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), first)
            self.assertEqual(json.loads(lines[1]), second)

    def test_read_records_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pickup.read_records(Path(tmp) / "nope.jsonl"), [])


class StageProposalMarkdownTests(unittest.TestCase):
    def test_contains_question_answer_wikilinks_and_ref(self):
        record = pickup.build_qa_record(
            sample_entry(),
            "Azure is the canonical home. The local copy is the working copy.",
            ["overview", "syntheses/decision-register"],
            "2026-10-13T12:05:00Z",
        )
        markdown = pickup.stage_proposal_markdown(record)
        self.assertIn("What is the wiki's canonical home?", markdown)
        self.assertIn("Azure is the canonical home.", markdown)
        self.assertIn("[[overview]]", markdown)
        self.assertIn("[[syntheses/decision-register]]", markdown)
        self.assertIn(AUTHORISATION_REF, markdown)
        self.assertIn(
            "Filed from the Lens Ask panel. Owner authorisation ref: "
            + AUTHORISATION_REF + ".",
            markdown,
        )
        # Frontmatter.
        self.assertTrue(markdown.startswith("---\n"))
        self.assertIn("type: query", markdown)
        self.assertIn("created: 2026-10-13", markdown)
        self.assertIn("updated: 2026-10-13", markdown)
        self.assertIn("sources: []", markdown)
        self.assertIn("tags: [lens-ask]", markdown)
        self.assertIn("## Sources used", markdown)


class LoadServiceTokenTests(unittest.TestCase):
    def test_reads_dummy_token_from_tmp_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (state_dir / "ask-service.token").write_text(
                "  dummy-token-for-tests\n", encoding="utf-8"
            )
            self.assertEqual(
                pickup.load_service_token(state_dir), "dummy-token-for-tests"
            )
            # str paths work too.
            self.assertEqual(
                pickup.load_service_token(str(state_dir)),
                "dummy-token-for-tests",
            )


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MarkAnsweredRequestTests(unittest.TestCase):
    def test_builds_right_request(self):
        captured = {}

        def fake_urlopen(request, *args, **kwargs):
            captured["request"] = request
            return FakeResponse(status=200, body=b'{"ok": true}')

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            result = pickup.mark_answered(
                "https://example.test/",
                "dummy-token-for-tests",
                "q_fixture0001",
                "wiki/access/qa-2026.jsonl#q_fixture0001",
            )

        self.assertEqual(result, {"ok": True})
        request = captured["request"]
        self.assertEqual(
            request.full_url,
            "https://example.test/api/questions/q_fixture0001/answered",
        )
        self.assertEqual(request.get_method(), "POST")
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.assertEqual(headers.get("x-ask-token"), "dummy-token-for-tests")
        self.assertEqual(headers.get("content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"answer_ref": "wiki/access/qa-2026.jsonl#q_fixture0001"},
        )


class RecordAnswerCliTests(unittest.TestCase):
    def test_record_answer_end_to_end(self):
        fixture = FIXTURES / "sample_answer.json"
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
            self.assertEqual(
                stdout.getvalue().strip(),
                "wiki/access/qa-2026.jsonl#q_fixture0001",
            )

            records = pickup.read_records(qa_file)
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["id"], "q_fixture0001")
            self.assertEqual(
                record["question"], "What is the wiki's canonical home?"
            )
            self.assertEqual(record["asker"], "owner@example.invalid")
            self.assertEqual(record["asked_at"], "2026-01-15T12:00:00Z")
            self.assertEqual(record["status"], "answered")
            self.assertTrue(record["answered_at"])
            self.assertEqual(
                record["citations"], ["overview", "syntheses/decision-register"]
            )
            self.assertIn("canonical home is its git remote", record["answer"])

            proposal = staging_dir / "qa-q_fixture0001.md"
            self.assertTrue(proposal.exists())
            content = proposal.read_text(encoding="utf-8")
            self.assertIn("What is the wiki's canonical home?", content)
            self.assertIn("[[overview]]", content)
            self.assertIn("[[syntheses/decision-register]]", content)
            self.assertIn(AUTHORISATION_REF, content)


class BuildQaRecordPackTests(unittest.TestCase):
    """the build remainder: mode, scored citations, trust verdict."""

    def test_mode_carried_from_question_entry(self):
        entry = sample_entry()
        entry["mode"] = "search"
        record = pickup.build_qa_record(
            entry, "Passages only.", ["overview"], "2026-10-20T12:05:00Z"
        )
        self.assertEqual(record["mode"], "search")

    def test_explicit_mode_argument_wins_and_invalid_mode_dropped(self):
        entry = sample_entry()
        entry["mode"] = "search"
        record = pickup.build_qa_record(
            entry, "A.", ["overview"], "2026-10-20T12:05:00Z",
            mode="deep-research",
        )
        self.assertEqual(record["mode"], "deep-research")
        record = pickup.build_qa_record(
            entry, "A.", ["overview"], "2026-10-20T12:05:00Z",
            mode="yolo",
        )
        self.assertNotIn("mode", record)

    def test_citation_details_and_verdict_stamped_when_supplied(self):
        details = [{
            "page": "overview", "score": 0.9,
            "passage": "Azure is the canonical home.",
        }]
        record = pickup.build_qa_record(
            sample_entry(), "Azure is the canonical home.",
            ["overview"], "2026-10-20T12:05:00Z",
            citation_details=details, trust_verdict="ok",
        )
        self.assertEqual(record["citation_details"], details)
        self.assertEqual(record["trust_verdict"], "ok")

    def test_proposal_markdown_shows_mode_verdict_and_passage(self):
        record = pickup.build_qa_record(
            sample_entry(), "Azure is the canonical home.",
            ["overview"], "2026-10-20T12:05:00Z",
            mode="answer",
            citation_details=[{
                "page": "overview", "score": 0.9,
                "passage": "Azure is the canonical home.",
            }],
            trust_verdict="ok",
        )
        markdown = pickup.stage_proposal_markdown(record)
        self.assertIn("**answer** mode", markdown)
        self.assertIn("Trust verdict: **ok**", markdown)
        self.assertIn("[[overview]] — relevance 0.9", markdown)
        self.assertIn("> Azure is the canonical home.", markdown)

    def test_record_answer_stamps_a_computed_verdict(self):
        # End to end through the CLI: a plain cited answer recorded
        # from the shipped fixture gains a trust_verdict, computed —
        # and the record still validates afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            qa_file = Path(tmp) / "qa-2026.jsonl"
            staging_dir = Path(tmp) / "staging"
            answer_file = Path(tmp) / "answer.json"
            payload = json.loads(
                (FIXTURES / "sample_answer.json").read_text(
                    encoding="utf-8"
                )
            )
            answer_file.write_text(
                json.dumps(payload), encoding="utf-8"
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = pickup.main([
                    "--qa-file", str(qa_file),
                    "--staging-dir", str(staging_dir),
                    "record-answer", "--answer-file", str(answer_file),
                ])
            self.assertEqual(rc, 0)
            records = pickup.read_records(qa_file)
            self.assertEqual(len(records), 1)
            self.assertIn(records[0]["trust_verdict"], ("ok", "review"))


if __name__ == "__main__":
    unittest.main()
