"""Tests for tools/ask/lessons.py (W5 lesson injection) and
its seams in pickup.py + provenance.py.

Pins:
  - the matching rule exactly as stated in lessons.py —
    >= 2 shared content terms OR >= 1 cited page the
    lesson's record names; one shared term is NOT a match;
    ordering page-overlap first, then shared-term count,
    then ledger order; cap of 3;
  - the lesson data is the lifecycle tool's own derivation
    over the real ledger (states/grades census unchanged:
    promoted 3, acted-on 4; landed 4, reproduced 1,
    ci-verified 1, reuse-observed 1) and does not vary with
    the as-of date the report is computed at;
  - a record with no matching lesson carries NO lessons
    block, and a proposal rendered from it is untouched by
    the seam; a record WITH a block renders the section,
    and removing exactly those lines reproduces the
    no-lessons rendering byte for byte (the injection
    cannot have changed the answer);
  - pickup stamps lessons only on an explicit payload or
    an emit_lessons flag — never by default;
  - the provenance envelope names the record's lessons
    when present and is silent otherwise.

Fixture-root tests use a temp dir (files are assembled by
copying the real seam scripts beside a two-entry fixture
ledger). Real-tree tests are read-only.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network.
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(ASK_DIR))

import lessons  # noqa: E402
import pickup  # noqa: E402
import provenance  # noqa: E402

FIXTURE_LEDGER = """# Corrections ledger (fixture)

## Entries

### 2026-09-01 — The phantom cache that does not exist

- **What was wrong:** a delivery claimed a cache existed;
  nothing in the product had been checked.
- **Standing rule:** never claim a cache exists unless it
  has been verified in the product itself.
- **Recorded:** [[cache-notes]]; `wiki/log.md`.

### 2026-09-02 — Counts delivered from a draft summary

- **What was wrong:** a count came from a draft summary,
  not from the artifact.
- **Standing rule:** deliver counts only from the artifact
  on disk, never from a draft summary.
- **Recorded:** `wiki/log.md`.

## Classification

| Entry | Class | Error kind | Standing rule |
|---|---|---|---|
| 2026-09-01 — The phantom cache that does not exist | correction | overstated-claim | verify-in-product |
| 2026-09-02 — Counts delivered from a draft summary | correction | overstated-claim | artifact-governs |
"""


def fixture_root(base: Path) -> Path:
    root = base / "fixture-wiki"
    (root / "wiki" / "rules").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "tools" / "ask").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "wiki" / "rules" / "corrections-ledger.md").write_text(
        FIXTURE_LEDGER, encoding="utf-8")
    for name in ("wiki_corrections.py",
                 "wiki_corrections_lifecycle.py",
                 "wiki_decision_records.py"):
        shutil.copy(ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy(ASK_DIR / "lessons.py", root / "tools" / "ask" / "lessons.py")
    return root


def fake_lesson(entry, tokens, pages=()):
    return {"entry": entry, "date": "2026-09-01", "title": entry,
            "class": "correction", "kind": "overstated-claim",
            "rule": "r-" + entry, "rule_text": "rule text",
            "state": "acted-on", "gate": "warning",
            "grade": "landed", "citation": lessons.LEDGER_REL,
            "tokens": sorted(tokens), "pages": sorted(pages)}


class MatchingRuleTests(unittest.TestCase):
    """The stated rule, on synthetic lessons (no ledger)."""

    def test_two_shared_terms_match(self):
        ls = [fake_lesson("L1", ["cache", "product", "verified"])]
        out = lessons.match_by_tokens(ls, {"cache", "product", "door"})
        self.assertEqual([m["entry"] for m in out], ["L1"])
        self.assertEqual(out[0]["basis"][0]["signal"], "shared-terms")
        self.assertEqual(out[0]["basis"][0]["count"], 2)

    def test_one_shared_term_is_not_a_match(self):
        ls = [fake_lesson("L1", ["cache", "product", "verified"])]
        self.assertEqual(
            lessons.match_by_tokens(ls, {"cache", "unrelated"}), [])

    def test_page_overlap_matches_alone(self):
        ls = [fake_lesson("L1", ["zzz"], pages=["cache-notes"])]
        out = lessons.match_by_tokens(
            ls, {"nothing", "shared"}, pages=["cache-notes"])
        self.assertEqual([m["entry"] for m in out], ["L1"])
        self.assertEqual(out[0]["basis"][0]["signal"], "page-overlap")

    def test_page_stem_normalisation(self):
        ls = [fake_lesson("L1", ["zzz"], pages=["cache-notes"])]
        out = lessons.match_by_tokens(
            ls, set(), pages=["cache-notes.md"])
        self.assertEqual(len(out), 1)

    def test_ordering_and_cap(self):
        ls = [
            fake_lesson("terms3", ["a1", "a2", "a3"]),
            fake_lesson("pagehit", ["zz"], pages=["p1"]),
            fake_lesson("terms2", ["a1", "a2"]),
            fake_lesson("terms4", ["a1", "a2", "a3", "a4"]),
        ]
        out = lessons.match_by_tokens(
            ls, {"a1", "a2", "a3", "a4"}, pages=["p1"])
        # page-overlap first, then shared-term count desc,
        # capped at MAX_LESSONS: terms2 (2 shared) falls off.
        self.assertEqual([m["entry"] for m in out],
                         ["pagehit", "terms4", "terms3"])
        self.assertEqual(len(out), lessons.MAX_LESSONS)


class FixtureLedgerTests(unittest.TestCase):
    """The engine over a two-entry fixture ledger."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = fixture_root(Path(cls._tmp.name))
        cls.lessons = lessons.load_lessons(cls.root, today="2026-09-03")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_both_entries_load_with_derived_fields(self):
        self.assertEqual(len(self.lessons), 2)
        first = self.lessons[0]
        self.assertEqual(first["rule"], "verify-in-product")
        self.assertEqual(first["kind"], "overstated-claim")
        self.assertEqual(first["state"], "acted-on")
        self.assertIn("cache-notes", first["pages"])
        self.assertIn("verified in the product itself",
                      first["rule_text"])

    def test_block_on_shared_terms(self):
        block = lessons.build_lessons_block(
            {"question": "Does the cache exist in the product?",
             "citations": []}, self.root, today="2026-09-03")
        self.assertIsNotNone(block)
        self.assertEqual(block["kind"], "ask-lessons")
        self.assertEqual(block["lessons_considered"], 2)
        self.assertEqual(block["matched"][0]["rule"],
                         "verify-in-product")

    def test_block_on_page_overlap_with_neutral_question(self):
        block = lessons.build_lessons_block(
            {"question": "Summarise this page please",
             "citations": ["cache-notes"]},
            self.root, today="2026-09-03")
        self.assertIsNotNone(block)
        self.assertEqual(block["matched"][0]["basis"][0]["signal"],
                         "page-overlap")

    def test_no_block_for_unrelated_question(self):
        self.assertIsNone(lessons.build_lessons_block(
            {"question": "What is the capital of France?",
             "citations": []}, self.root, today="2026-09-03"))

    def test_render_quotes_the_rule_verbatim(self):
        block = lessons.build_lessons_block(
            {"question": "Does the cache exist in the product?",
             "citations": []}, self.root, today="2026-09-03")
        lines = lessons.render_lessons({"lessons": block})
        text = "\n".join(lines)
        self.assertIn("## Lessons on record", text)
        self.assertIn("never claim a cache exists unless it",
                      text)
        self.assertIn("wiki/rules/corrections-ledger.md", text)

    def test_missing_ledger_is_a_named_door(self):
        with self.assertRaises(FileNotFoundError):
            lessons.load_lessons(self.root / "no-such-tree")


class RealLedgerTests(unittest.TestCase):
    """Read-only over the real tree: the derivation is the
    lifecycle tool's own census, and matching is honest."""

    @classmethod
    def setUpClass(cls):
        cls.lessons = lessons.load_lessons(ROOT)
        if not cls.lessons:
            # WikiCitadel's corrections ledger stands empty
            # (created 2026-10-22); the census/matching pins
            # below describe a populated ledger — the private
            # tree's, whose entries never port.
            raise unittest.SkipTest(
                "this tree's ledger stands empty — no lessons "
                "on record to census")

    def test_seven_lessons_census_unchanged(self):
        self.assertEqual(len(self.lessons), 7)
        states = [l["state"] for l in self.lessons]
        self.assertEqual(states.count("promoted-to-rule"), 3)
        self.assertEqual(states.count("acted-on"), 4)
        grades = [l["grade"] for l in self.lessons]
        self.assertEqual(grades.count("landed"), 4)
        self.assertEqual(grades.count("reproduced"), 1)
        self.assertEqual(grades.count("ci-verified"), 1)
        self.assertEqual(grades.count("reuse-observed"), 1)

    def test_derivation_does_not_vary_with_today(self):
        other = lessons.load_lessons(ROOT, today=date(2027, 1, 1))
        self.assertEqual(self.lessons, other)

    def test_interim_summary_question_matches_the_lesson(self):
        matched = lessons.match_by_tokens(
            self.lessons,
            lessons.question_tokens(
                ROOT, "Should the counts come from the interim "
                      "summary or the artifact on disk?"))
        rules = [m["rule"] for m in matched]
        self.assertIn("artifact-governs", rules)
        gate = {m["rule"]: m["gate"] for m in matched}
        self.assertEqual(gate["artifact-governs"], "blocking")

    def test_one_shared_term_does_not_match(self):
        matched = lessons.match_by_tokens(
            self.lessons,
            lessons.question_tokens(ROOT, "What did the validator say?"))
        self.assertEqual(matched, [])

    def test_unrelated_question_matches_nothing(self):
        matched = lessons.match_by_tokens(
            self.lessons,
            lessons.question_tokens(
                ROOT, "What is the capital of France?"))
        self.assertEqual(matched, [])

    def test_citing_the_ideas_page_surfaces_its_lessons(self):
        # Two entries' records name [[ideas]]: the ask-first
        # entry (its Recorded line) and the 2026-10-20
        # recurrence entry (its body). Both are genuine
        # page-overlap matches; ledger order breaks the tie.
        matched = lessons.match_by_tokens(
            self.lessons,
            lessons.question_tokens(
                ROOT, "What is the capital of France?"),
            pages=["ideas"])
        self.assertEqual([m["rule"] for m in matched],
                         ["ask-first", "artifact-governs"])
        self.assertEqual(matched[0]["basis"][0]["signal"],
                         "page-overlap")


class PickupSeamTests(unittest.TestCase):
    """The additive seam: default records are untouched;
    the block appears only when the payload asks for it."""

    ENTRY = {"id": "q_lessons_test", "question": "Panel question",
             "asker": "test", "asked_at": "2026-10-22T00:00:00Z"}

    def _record(self):
        return pickup.build_qa_record(
            self.ENTRY, "An answer.", ["chapter7-decisions"],
            "2026-10-22T01:00:00Z")

    def test_default_payload_stamps_nothing(self):
        record = self._record()
        self.assertNotIn("lessons", record)
        self.assertIsNone(pickup._payload_lessons({}, record))
        self.assertNotIn("lessons", record)

    def test_explicit_block_stamped_as_is(self):
        block = {"kind": "ask-lessons", "matched": []}
        self.assertIs(
            pickup._payload_lessons({"lessons": block}, self._record()),
            block)

    def test_emit_lessons_builds_from_the_record(self):
        if not lessons.load_lessons(ROOT):
            self.skipTest("this tree's ledger stands empty — "
                          "no lessons to emit")
        record = self._record()
        record["question"] = ("Can I trust the interim summary "
                              "from the building agent?")
        block = pickup._payload_lessons({"emit_lessons": True}, record)
        self.assertIsNotNone(block)
        self.assertEqual(block["lessons_considered"], 7)
        self.assertIn("artifact-governs",
                      [m["rule"] for m in block["matched"]])

    def test_proposal_rendering_byte_stable_without_block(self):
        record = self._record()
        plain = pickup.stage_proposal_markdown(record)
        self.assertNotIn("## Lessons on record", plain)
        block = {"kind": "ask-lessons", "version": 1,
                 "matched": [{
                     "entry": "2026-09-01 — Fixture",
                     "date": "2026-09-01", "title": "Fixture lesson",
                     "rule": "verify-in-product",
                     "kind": "overstated-claim",
                     "class": "correction", "state": "acted-on",
                     "gate": "warning", "grade": "landed",
                     "rule_text": "the fixture rule text",
                     "citation": "wiki/rules/corrections-ledger.md",
                     "basis": [{"signal": "shared-terms",
                                "terms": ["cache", "product"],
                                "count": 2}]}]}
        record2 = dict(record)
        record2["lessons"] = block
        dressed = pickup.stage_proposal_markdown(record2)
        self.assertIn("## Lessons on record", dressed)
        self.assertIn("the fixture rule text", dressed)
        # Removing exactly the seam's lines restores the
        # plain rendering byte for byte.
        lesson_lines = pickup._lesson_lines(record2)
        lines = dressed.split("\n")
        start = lines.index("## Lessons on record")
        del lines[start:start + len(lesson_lines)]
        self.assertEqual("\n".join(lines), plain)

    def test_provenance_envelope_names_lessons(self):
        record = self._record()
        record["lessons"] = {
            "kind": "ask-lessons",
            "matched": [{"entry": "2026-10-19 — Fixture",
                         "rule": "artifact-governs",
                         "state": "promoted-to-rule"}]}
        env = provenance.build_provenance(
            record, wiki_dir=ROOT / "wiki", root=ROOT)
        self.assertEqual(env["lessons"]["count"], 1)
        self.assertEqual(env["lessons"]["entries"][0]["rule"],
                         "artifact-governs")
        env2 = provenance.build_provenance(
            self._record(), wiki_dir=ROOT / "wiki", root=ROOT)
        self.assertNotIn("lessons", env2)


if __name__ == "__main__":
    unittest.main()
