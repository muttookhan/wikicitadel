"""Tests for tools/ask/reading_notes.py (Marathon R4 lane D, item 3).

Pins: the flag defaults OFF and an off record is returned
unchanged (no notes field, same object); with the flag on, one
deterministic extractive note per retrieved page is produced —
matched query terms plus the page's own summary line, no model
calls; the record gains only the additive ``notes`` field and
still passes the unchanged answer contract with the flag off
and on; notes are deterministic and inputs are never mutated.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network is used.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import answer_contract  # noqa: E402
import reading_notes  # noqa: E402

PASSAGE = "Azure is the canonical home of the wiki. Extra detail follows here."
PACKED = [
    {"page": "overview", "passage": PASSAGE, "score": 0.95},
    {"page": "other", "passage": "Unrelated passage about baking bread.", "score": 0.4},
]
QUESTION = "Where is the canonical home of the wiki?"


def make_wiki(tmp):
    wiki = Path(tmp) / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "overview.md").write_text(
        "---\ntitle: Overview\n---\n\n" + PASSAGE + "\n", encoding="utf-8")
    (wiki / "other.md").write_text(
        "---\ntitle: Other\n---\n\nUnrelated passage about baking bread.\n",
        encoding="utf-8")
    return wiki


def record():
    return {
        "question": QUESTION,
        "answer": "The wiki lives on Azure.",
        "citations": ["overview"],
        "citation_details": [
            {"page": "overview", "score": 0.9, "passage": PASSAGE}],
    }


class FlagTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        self.assertFalse(reading_notes.reading_notes_enabled())
        self.assertFalse(reading_notes.reading_notes_enabled({}))
        self.assertFalse(reading_notes.reading_notes_enabled({"reading_notes": False}))
        self.assertTrue(reading_notes.reading_notes_enabled({"reading_notes": True}))
        self.assertTrue(reading_notes.reading_notes_enabled({}, enabled=True))


class AttachTests(unittest.TestCase):
    def test_off_returns_record_unchanged(self):
        rec = record()
        out = reading_notes.attach_reading_notes(rec, PACKED, QUESTION)
        self.assertIs(out, rec)
        self.assertNotIn("notes", out)

    def test_on_adds_one_note_per_page_and_does_not_mutate(self):
        rec = record()
        out = reading_notes.attach_reading_notes(
            rec, PACKED, QUESTION, enabled=True)
        self.assertIsNot(out, rec)
        self.assertNotIn("notes", rec)
        self.assertEqual(len(out["notes"]), 2)
        first, second = out["notes"]
        self.assertEqual(first["page"], "overview")
        self.assertIn("canonical", first["matched_terms"])
        self.assertIn("home", first["matched_terms"])
        self.assertEqual(first["summary"], PASSAGE.split(". ")[0] + ".")
        self.assertIn("canonical", first["note"])
        self.assertEqual(second["matched_terms"], [])
        self.assertEqual(reading_notes.validate_reading_notes(out), [])

    def test_flag_on_via_record_field(self):
        rec = record(); rec["reading_notes"] = True
        out = reading_notes.attach_reading_notes(rec, PACKED)
        self.assertIn("notes", out)
        # Question defaults to the record's own question field.
        self.assertIn("canonical", out["notes"][0]["matched_terms"])

    def test_notes_are_deterministic(self):
        a = reading_notes.build_reading_notes(PACKED, QUESTION)
        b = reading_notes.build_reading_notes(PACKED, QUESTION)
        self.assertEqual(a, b)

    def test_record_stays_valid_off_and_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            off = reading_notes.attach_reading_notes(record(), PACKED, QUESTION)
            self.assertEqual(answer_contract.validate_answer(off, wiki), [])
            on = reading_notes.attach_reading_notes(
                record(), PACKED, QUESTION, enabled=True)
            self.assertEqual(answer_contract.validate_answer(on, wiki), [])
            self.assertEqual(reading_notes.validate_reading_notes(on), [])

    def test_supplied_summary_wins_over_passage(self):
        notes = reading_notes.build_reading_notes(
            [{"page": "p", "passage": "First sentence. Second.",
              "summary": "The retriever's own summary line."}], "question")
        self.assertEqual(notes[0]["summary"], "The retriever's own summary line.")

    def test_malformed_notes_are_flagged(self):
        self.assertTrue(reading_notes.validate_reading_notes({"notes": "nope"}))
        self.assertTrue(reading_notes.validate_reading_notes(
            {"notes": [{"page": "", "matched_terms": [], "note": ""}]}))
        self.assertEqual(reading_notes.validate_reading_notes({}), [])


if __name__ == "__main__":
    unittest.main()
