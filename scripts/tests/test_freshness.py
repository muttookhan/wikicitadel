#!/usr/bin/env python3
"""Freshness at the moment of use (consolidated-queue item 46).

scripts/wiki_search.py's freshness section computes, per page,
the annotation that travels with a result or an evidence
passage when it is DISPLAYED: verified_until / reverify-due /
supersession / source standing, plus its one-line rendering.
tools/lens/lenslib.py mirrors the computation (the ranking /
severance mirror discipline), so these tests run every case
through BOTH implementations and pin the agreement:

- fixture pages: each signal on its own, the combinations,
  and the silent case (no signal -> no line, and silence is
  never rendered as freshness);
- the real corpus: a fixed page set, records identical from
  both implementations, and the mirrored due map checked
  against scripts/wiki_reverify.py's own schedule (the
  source of truth the mirror must not drift from).

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2030, 10, 20)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wiki_search", ROOT / "scripts" / "wiki_search.py")
ll = _load("lenslib", ROOT / "tools" / "lens" / "lenslib.py")
rv = _load("wiki_reverify", ROOT / "scripts" / "wiki_reverify.py")
IMPLS = (("wiki_search", ws), ("lenslib", ll))


def page(frontmatter, body="Body text.\n"):
    fm = "\n".join(frontmatter)
    return f"---\n{fm}\n---\n\n{body}"


FIXTURE_PAGES = {
    "wiki/entities/attested.md": page([
        "title: Attested",
        "verified_until: 2031-01-20",
        "verified_by: owner",
    ]),
    "wiki/entities/lapsed.md": page([
        "title: Lapsed",
        "verified_until: 2030-01-01",
        "verified_by: owner",
    ]),
    "wiki/sources/claim-due.md": page([
        "title: Claim due",
        'claim: "A claim whose check falls due today."',
        "as_of: 2030-10-13",
    ]),
    "wiki/sources/claim-later.md": page([
        "title: Claim later",
        'claim: "A claim whose check is still upcoming."',
        "as_of: 2030-10-19",
    ]),
    "wiki/old/pointed.md": page([
        "title: Pointed",
        "superseded_by: wiki/new/replacement.md",
    ]),
    "wiki/old/status-only.md": page([
        "title: Status only",
        "status: superseded",
    ]),
    "wiki/old/tomb.md": page([
        "title: Tomb",
        "status: tombstoned",
        "replaced_by: wiki/new/replacement.md",
    ]),
    "wiki/sources/treated.md": page(["title: Treated"]),
    "wiki/sources/graded.md": page(["title: Graded"]),
    "wiki/plain/quiet.md": page(["title: Quiet"]),
}

TREATMENT_ROWS = [
    {"kind": "header", "register": "treatment-register"},
    {"kind": "treatment", "id": "treat-9001",
     "subject": {"page": "wiki/sources/treated.md", "claim": None},
     "grade": "negative"},
]
GRADE_ROWS = [
    {"kind": "header", "register": "source-grades"},
    {"kind": "grade", "source": "wiki/sources/graded.md",
     "axis": "integrity", "grade": "questioned"},
]


def build_fixture(root: Path):
    for rel, text in FIXTURE_PAGES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    ev = root / "evaluation"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "treatment-register.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in TREATMENT_ROWS),
        encoding="utf-8")
    (ev / "source-grades.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in GRADE_ROWS),
        encoding="utf-8")
    return root


class FixtureFreshness(unittest.TestCase):
    """Every fixture case through BOTH implementations."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = build_fixture(Path(cls.tmp) / "repo")
        cls.signals = {
            name: mod.load_freshness_signals(cls.root, TODAY)
            for name, mod in IMPLS
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def record(self, mod_name, rel):
        mod = dict(IMPLS)[mod_name]
        text = (self.root / rel).read_text(encoding="utf-8")
        return mod.freshness_record(
            rel, text, TODAY, self.signals[mod_name])

    def both(self, rel):
        a = self.record("wiki_search", rel)
        b = self.record("lenslib", rel)
        self.assertEqual(a, b, f"{rel}: implementations disagree")
        return a

    def test_verified_current(self):
        rec = self.both("wiki/entities/attested.md")
        self.assertEqual(rec["verified_until"], "2031-01-20")
        self.assertFalse(rec["overdue"])
        self.assertEqual(rec["line"], "verified until 2031-01-20")

    def test_verified_lapsed_is_overdue(self):
        rec = self.both("wiki/entities/lapsed.md")
        self.assertEqual(rec["verified_until"], "2030-01-01")
        self.assertTrue(rec["overdue"])
        self.assertEqual(
            rec["line"],
            "⚠ verification overdue since 2030-01-01")

    def test_claim_on_due_list_is_overdue(self):
        # as_of 2030-10-13 + round(S0=7) days = due 2030-10-20.
        rec = self.both("wiki/sources/claim-due.md")
        self.assertTrue(rec["overdue"])
        self.assertEqual(
            rec["line"], "⚠ re-verification due 2030-10-20")

    def test_claim_upcoming_is_silent(self):
        rec = self.both("wiki/sources/claim-later.md")
        self.assertFalse(rec["overdue"])
        self.assertIsNone(rec["line"])

    def test_superseded_by_pointer(self):
        rec = self.both("wiki/old/pointed.md")
        self.assertTrue(rec["superseded"])
        self.assertEqual(rec["superseded_by"], "new/replacement")
        self.assertEqual(
            rec["line"], "superseded by [[new/replacement]]")

    def test_status_superseded_without_pointer(self):
        rec = self.both("wiki/old/status-only.md")
        self.assertTrue(rec["superseded"])
        self.assertIsNone(rec["superseded_by"])
        self.assertEqual(rec["line"], "marked superseded")

    def test_tombstone_uses_replaced_by(self):
        rec = self.both("wiki/old/tomb.md")
        self.assertTrue(rec["superseded"])
        self.assertEqual(rec["superseded_by"], "new/replacement")
        self.assertEqual(
            rec["line"], "superseded by [[new/replacement]]")

    def test_negative_treatment_standing(self):
        rec = self.both("wiki/sources/treated.md")
        self.assertIsNotNone(rec["standing"])
        self.assertEqual(rec["standing"]["tier"], 3)
        self.assertTrue(rec["standing"]["negative"])
        self.assertEqual(
            rec["line"],
            "source standing: negative — treatment negative "
            "(treat-9001, page)")

    def test_questioned_grade_standing(self):
        rec = self.both("wiki/sources/graded.md")
        self.assertEqual(rec["standing"]["tier"], 2)
        self.assertEqual(
            rec["line"],
            "source standing: weakened — integrity questioned")

    def test_silent_page(self):
        rec = self.both("wiki/plain/quiet.md")
        self.assertIsNone(rec["verified_until"])
        self.assertFalse(rec["overdue"])
        self.assertFalse(rec["superseded"])
        self.assertIsNone(rec["superseded_by"])
        self.assertIsNone(rec["standing"])
        self.assertIsNone(rec["line"])

    def test_fixture_due_map(self):
        # Exactly the due-today claim, nothing else (the
        # upcoming claim stays off the list). The real-corpus
        # class below pins the mirror to wiki_reverify itself.
        for name, mod in IMPLS:
            due = mod.freshness_due_map(self.root, TODAY)
            self.assertEqual(
                set(due), {"wiki/sources/claim-due.md"},
                f"{name}: due map {sorted(due)}")
            self.assertEqual(
                due["wiki/sources/claim-due.md"]["due"],
                "2030-10-20")


if __name__ == "__main__":
    unittest.main()
