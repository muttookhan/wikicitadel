#!/usr/bin/env python3
"""Pins wiki_eval_draft (Marathon R5 lane BB; Giskard RAGET
pattern): drafts are generated deterministically from compiled
pages, land ONLY under staging/eval-drafts/, are marked
unapproved on their face, and the golden set stays
byte-untouched — including under direct attack (an --out at
the golden set, at evaluation/, or at an existing file is
refused and writes nothing).

Run:  python3 -m unittest discover -s scripts/tests
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wiki_eval_draft", SCRIPTS / "wiki_eval_draft.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PAGE = """---
title: Harbour Lights
type: source
created: 2026-01-15
updated: 2026-01-15
sources: [raw/sources/harbour.md]
tags: [fixture]
claim: "The harbour light flashes twice every ten seconds throughout the night for approaching boats."
---

## Operation

The harbour light flashes twice every ten seconds throughout
the night for approaching boats.^[cite: raw/sources/harbour.md#L3-L4]
The keeper records each lamp change in the harbour log book
beside the tower door.^[cite: raw/sources/harbour.md#L5-L6]
An uncited remark about gulls that carries no marker at all
and should never become a drafted question on its own here.
"""

GOLDEN = '{"id": "GQ-001", "question": "keep me"}\n'


def build_root(tmp):
    root = Path(tmp)
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    (root / "staging" / "eval-drafts").mkdir(parents=True)
    (root / "wiki" / "sources" / "harbour.md").write_text(PAGE)
    (root / "evaluation" / "golden-questions.jsonl").write_text(GOLDEN)
    return root


class TestEvalDraft(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build_root(self.tmp.name)
        self.golden = self.root / "evaluation" / "golden-questions.jsonl"
        self.h = hashlib.sha256(self.golden.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def golden_ok(self):
        self.assertEqual(
            hashlib.sha256(self.golden.read_bytes()).hexdigest(),
            self.h)

    def test_drafts_generated_marked_unapproved(self):
        out = "staging/eval-drafts/harbour-drafts.jsonl"
        rc = m.main(["--root", str(self.root), "draft",
                     "wiki/sources/harbour.md", "--out", out,
                     "--date", "2026-10-21"])
        self.assertEqual(rc, 0)
        rows = [json.loads(l) for l in
                (self.root / out).read_text().splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "draft" for r in rows))
        self.assertTrue(all(r["approved"] is False for r in rows))
        self.assertTrue(all(r["origin"] == "wiki_eval_draft"
                            for r in rows))
        self.assertTrue(any(r["kind"] == "citation-recall"
                            for r in rows))
        self.assertTrue(any(r["kind"] == "claim-check"
                            for r in rows))
        # answerability: every expected answer is in the page
        page_text = (self.root / "wiki/sources/harbour.md").read_text()
        for r in rows:
            self.assertIn(m.norm(r["expected_answer"]),
                          m.norm(page_text))
        # the uncited gull remark drafted nothing
        self.assertFalse(any("gulls" in r["question"]
                             for r in rows))
        self.golden_ok()

    def test_deterministic(self):
        a, _ = m.draft_from_page(self.root, "wiki/sources/harbour.md", 0)
        b, _ = m.draft_from_page(self.root, "wiki/sources/harbour.md", 0)
        self.assertEqual(a, b)

    def test_refuses_golden_path(self):
        rc = m.main(["--root", str(self.root), "draft",
                     "wiki/sources/harbour.md", "--out",
                     "evaluation/golden-questions.jsonl",
                     "--date", "2026-10-21"])
        self.assertEqual(rc, 4)
        self.golden_ok()

    def test_refuses_outside_staging(self):
        for bad in ("evaluation/drafts.jsonl", "wiki/drafts.jsonl",
                    "staging/other.jsonl", "drafts.jsonl"):
            rc = m.main(["--root", str(self.root), "draft",
                         "wiki/sources/harbour.md", "--out", bad,
                         "--date", "2026-10-21"])
            self.assertEqual(rc, 4, bad)
            self.assertFalse((self.root / bad).exists(), bad)
        self.golden_ok()

    def test_refuses_overwrite_and_golden_name(self):
        out = self.root / "staging" / "eval-drafts" / "x.jsonl"
        out.write_text("existing\n")
        rc = m.main(["--root", str(self.root), "draft",
                     "wiki/sources/harbour.md", "--out",
                     "staging/eval-drafts/x.jsonl",
                     "--date", "2026-10-21"])
        self.assertEqual(rc, 4)
        self.assertEqual(out.read_text(), "existing\n")
        rc = m.main(["--root", str(self.root), "draft",
                     "wiki/sources/harbour.md", "--out",
                     "staging/eval-drafts/golden-questions.jsonl",
                     "--date", "2026-10-21"])
        self.assertEqual(rc, 4)
        self.golden_ok()


if __name__ == "__main__":
    unittest.main()
