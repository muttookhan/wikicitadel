"""Tests for the "Show me the chunks" debug view (Marathon R2
lane B1).

``tools/ask/show_chunks.py`` lists the exact evidence chunks
packed for a recorded answer — page, § anchor, score and the
verbatim first line of each chunk — from the record's
``citation_details`` (or an embedded pack result).

Run from the repo root:
    python3 -m unittest tools.ask.tests.test_show_chunks -v
or directly:
    python3 tools/ask/tests/test_show_chunks.py

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

import show_chunks  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_record():
    return json.loads(
        (FIXTURES / "sample_chunks_record.json").read_text(
            encoding="utf-8"
        )
    )


class ChunksForRecordTests(unittest.TestCase):
    def test_chunks_from_citation_details(self):
        chunks = show_chunks.chunks_for_record(fixture_record())
        self.assertEqual(len(chunks), 2)
        first, second = chunks
        self.assertEqual(first["page"], "overview")
        self.assertEqual(first["anchor"], "founding")
        self.assertEqual(first["score"], 0.9)
        # Verbatim first line only — not the whole passage.
        self.assertEqual(
            first["first_line"], "First line of the overview chunk."
        )
        self.assertEqual(second["page"], "sources/note")
        self.assertEqual(second["anchor"], "")
        self.assertEqual(second["score"], 0.75)
        self.assertEqual(
            second["first_line"], "Only line of the note chunk."
        )

    def test_chunks_from_sub_answers_and_embedded_pack(self):
        record = {
            "citation_details": [
                {"page": "a", "score": 0.5, "passage": "Top chunk."},
            ],
            "sub_answers": [{
                "citation_details": [
                    {"page": "b", "score": 0.6,
                     "passage": "Sub chunk."},
                ],
            }],
        }
        chunks = show_chunks.chunks_for_record(record)
        self.assertEqual([c["page"] for c in chunks], ["a", "b"])
        packed_record = {
            "packed": [
                {"page": "p", "score": 0.7, "section": "methods",
                 "passage": "Packed chunk line."},
            ],
            "citation_details": [
                {"page": "ignored", "passage": "Not packed."},
            ],
        }
        chunks = show_chunks.chunks_for_record(packed_record)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["anchor"], "methods")
        self.assertEqual(
            chunks[0]["first_line"], "Packed chunk line."
        )

    def test_record_without_chunks(self):
        self.assertEqual(show_chunks.chunks_for_record({}), [])
        self.assertIn(
            "no packed chunks recorded",
            show_chunks.format_chunks({"id": "q_x"}),
        )


class FormatAndCliTests(unittest.TestCase):
    def test_format_lists_page_anchor_score_first_line(self):
        listing = show_chunks.format_chunks(fixture_record())
        self.assertIn("q_chunks0001", listing)
        self.assertIn(
            "1. overview §founding score=0.90 — "
            "First line of the overview chunk.",
            listing,
        )
        # No anchor on the record: §—, never an invented anchor.
        self.assertIn(
            "2. sources/note §— score=0.75 — "
            "Only line of the note chunk.",
            listing,
        )

    def test_cli_on_fixture_record(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = show_chunks.main(
                [str(FIXTURES / "sample_chunks_record.json")]
            )
        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("overview §founding score=0.90", out)
        self.assertIn("Only line of the note chunk.", out)

    def test_cli_on_jsonl_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qa.jsonl"
            record = fixture_record()
            path.write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = show_chunks.main([str(path)])
            self.assertEqual(rc, 0)
            self.assertIn("q_chunks0001", stdout.getvalue())

    def test_cli_missing_file_is_an_error_not_a_traceback(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = show_chunks.main(["/nonexistent/record.json"])
        self.assertEqual(rc, 1)
        self.assertIn("show_chunks:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
