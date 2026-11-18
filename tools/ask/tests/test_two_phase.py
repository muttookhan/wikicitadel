"""Tests for tools/ask/two_phase.py (Marathon R3 lane TB1, row 2).

Pins: the flag defaults OFF; a preliminary is marked unverified
and may never be presented as a final; phase 2 re-opens the
cited pages and verifies each rich citation's passage
verbatim; a failed passage turns the final into an explicit
abstention (the gate is not weakened); a user correction
forces a second verification run with the preliminary
superseded, and a corrected final that skips re-verification
fails validate_two_phase; a clean final still passes the
unchanged abstention contract.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
Fixtures are tiny temp wiki trees; no network.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import answer_contract  # noqa: E402
import two_phase  # noqa: E402

PASSAGE = "Azure is the canonical home of the wiki."


def make_wiki(tmp):
    wiki = Path(tmp) / "wiki"
    (wiki / "syntheses").mkdir(parents=True)
    (wiki / "overview.md").write_text(
        "---\ntitle: Overview\n---\n\n" + PASSAGE + "\n",
        encoding="utf-8")
    return wiki


def entry():
    return {"id": "q_tp1", "question": "Where does the wiki live?",
            "asker": "owner@example.invalid",
            "asked_at": "2026-10-21T00:00:00Z"}


def final_payload():
    return {
        "question_entry": entry(),
        "answer": "The wiki lives on Azure.",
        "citations": ["overview"],
        "citation_details": [
            {"page": "overview", "score": 0.9, "passage": PASSAGE}],
    }


class FlagTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        self.assertFalse(two_phase.two_phase_enabled())
        self.assertFalse(two_phase.two_phase_enabled({}))
        self.assertFalse(two_phase.two_phase_enabled({"two_phase": False}))
        self.assertTrue(two_phase.two_phase_enabled({"two_phase": True}))


class PreliminaryTests(unittest.TestCase):
    def test_preliminary_is_marked_unverified(self):
        pre = two_phase.make_preliminary(entry(), "Draft.", ["overview"])
        self.assertEqual(pre["phase"], "preliminary")
        self.assertFalse(pre["verified"])
        self.assertIn("UNVERIFIED", pre["banner"])
        self.assertEqual(two_phase.validate_two_phase(pre), [])

    def test_preliminary_cannot_pose_as_final(self):
        pre = two_phase.make_preliminary(entry(), "Draft.", ["overview"])
        pre["status"] = "answered"
        self.assertTrue(two_phase.validate_two_phase(pre))


class VerifyFinalTests(unittest.TestCase):
    def test_clean_final_verifies_and_passes_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            pre = two_phase.make_preliminary(
                entry(), "Draft.", ["overview"])
            final = two_phase.verify_final(pre, final_payload(), wiki)
            self.assertTrue(final["verified"])
            self.assertEqual(final["phase"], "final")
            self.assertEqual(final["verification"]["claims"],
                             [{"page": "overview", "status": "verified"}])
            self.assertEqual(two_phase.validate_two_phase(final), [])
            self.assertEqual(
                answer_contract.validate_answer(final, wiki), [])

    def test_failed_passage_becomes_abstention(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            payload = final_payload()
            payload["citation_details"] = [
                {"page": "overview", "score": 0.9,
                 "passage": "This sentence is not in the page."}]
            final = two_phase.verify_final(
                two_phase.make_preliminary(entry(), "D.", ["overview"]),
                payload, wiki)
            self.assertFalse(final["verified"])
            self.assertTrue(final["abstained"])
            self.assertIn("claim verification failed",
                          final["abstention_reason"])
            # The abstention itself satisfies the contract.
            self.assertEqual(
                answer_contract.validate_answer(final, wiki), [])

    def test_correction_forces_reverification(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = make_wiki(tmp)
            pre = two_phase.make_preliminary(
                entry(), "Draft.", ["overview"])
            final = two_phase.verify_final(
                pre, final_payload(), wiki,
                correction="No — I mean the public wiki.")
            self.assertTrue(final["verified"])
            self.assertEqual(final["verification"]["runs"], 2)
            self.assertTrue(
                final["verification"]["correction_applied"])
            self.assertTrue(
                final["verification"]["preliminary_superseded"])
            self.assertEqual(two_phase.validate_two_phase(final), [])

    def test_corrected_final_without_rerun_is_refused(self):
        record = {
            "phase": "final", "verified": True,
            "verification": {"runs": 1, "correction_applied": False,
                             "correction": "use the other source"},
        }
        errors = two_phase.validate_two_phase(record)
        self.assertTrue(any("re-verification" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
