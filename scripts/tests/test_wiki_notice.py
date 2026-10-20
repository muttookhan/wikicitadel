"""Tests for scripts/wiki_notice.py (item 50): fixed-text
enforcement, apply/retire discipline, the mechanical suggest
rules, and the protocol-tier composition."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import wiki_notice as wn  # noqa: E402

VOCAB_SRC = SCRIPTS.parent / "evaluation" / "notice-vocabulary.json"

PAGE = """---
title: "%s"
type: %s
created: 2030-10-20
updated: 2030-10-20
sources:
%s
tags: [test]
---

# %s

Body text.
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="notice-fix-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        ev = self.root / "evaluation"
        ev.mkdir(parents=True)
        shutil.copy(VOCAB_SRC, ev / "notice-vocabulary.json")
        # grades: srcq graded integrity questioned
        write(ev / "source-grades.jsonl",
              json.dumps({"kind": "header"}) + "\n" +
              json.dumps({"kind": "grade",
                          "source": "wiki/sources/srcq.md",
                          "axis": "integrity",
                          "grade": "questioned"}) + "\n")
        # treatment: one negative on wiki/syntheses/neg.md
        write(ev / "treatment-register.jsonl",
              json.dumps({"kind": "header"}) + "\n" +
              json.dumps({"kind": "treatment", "id": "treat-x",
                          "grade": "negative",
                          "subject": {"page": "wiki/syntheses/neg.md",
                                      "claim": "c"}}) + "\n")
        # decisions register: header only (gate finds no forms)
        write(ev / "decisions-register.jsonl",
              json.dumps({"kind": "header"}) + "\n")
        w = self.root / "wiki"
        write(w / "sources" / "srcq.md",
              PAGE % ("Q", "source", "  - raw/q.md", "Q"))
        write(w / "concepts" / "fromq.md",
              PAGE % ("FromQ", "concept", "  - raw/q.md", "FromQ"))
        write(w / "syntheses" / "neg.md",
              PAGE % ("Neg", "synthesis", "  - raw/n.md", "Neg"))
        write(w / "syntheses" / "bare.md",
              PAGE % ("Bare", "synthesis", "", "Bare"))
        # identity-scopes fixture
        write(w / "access" / "identity-scopes.md", """---
title: "fixture"
---

| Identity | Scopes | Read prefixes | Source prefixes | Token |
|---|---|---|---|---|
| agent1 | wiki:read, wiki:propose, wiki:publish | - | - | **issued 2030-10-13** |
| filer1 | none issued to date | - | - | seat only |
""")
        write(w / "filings" / "filer1-filings.md", "# ledger\n")
        write(w / "access" / "black-box-2030.jsonl",
              json.dumps({"actor": "agent1"}) + "\n")


class ApplyTests(Fixture):
    def test_apply_inserts_exact_fixed_text(self):
        wn.apply_notice("wiki/sources/srcq.md",
                        "source-integrity-questioned",
                        reason="fixture grade", root=self.root)
        text = (self.root / "wiki/sources/srcq.md").read_text()
        vocab = wn.load_vocab(self.root)
        notice = vocab["source-integrity-questioned"]
        self.assertIn("> " + notice["fixed_text"], text)
        self.assertIn("<!-- notice:begin "
                      "id=source-integrity-questioned -->", text)
        # page otherwise intact
        self.assertIn("# Q", text)
        self.assertIn("Body text.", text)
        # block sits at the head of the body, before the H1
        self.assertLess(text.index("notice:begin"),
                        text.index("# Q"))

    def test_apply_refuses_unknown_id_and_repeat(self):
        with self.assertRaises(wn.NoticeError):
            wn.apply_notice("wiki/sources/srcq.md", "no-such",
                            reason="x", root=self.root)
        wn.apply_notice("wiki/sources/srcq.md",
                        "source-integrity-questioned",
                        reason="x", root=self.root)
        with self.assertRaises(wn.NoticeError):
            wn.apply_notice("wiki/sources/srcq.md",
                            "source-integrity-questioned",
                            reason="x", root=self.root)

    def test_caller_cannot_supply_text(self):
        # compose_block takes wording only from the vocabulary
        vocab = wn.load_vocab(self.root)
        block = wn.compose_block(vocab["attribution-incomplete"],
                                 "2030-10-20", "agent", "r")
        self.assertIn(vocab["attribution-incomplete"]
                      ["fixed_text"], block)

    def test_tampered_fixed_text_is_detected(self):
        wn.apply_notice("wiki/sources/srcq.md",
                        "source-integrity-questioned",
                        reason="x", root=self.root)
        page = self.root / "wiki/sources/srcq.md"
        page.write_text(page.read_text().replace(
            "stands unverified", "stands totally verified"))
        rows = wn.list_notices(self.root)
        self.assertEqual(rows[0][4], "FIXED TEXT ALTERED on page")
        self.assertEqual(wn.main(["--root", str(self.root),
                                  "check"]), 1)


class RetireTests(Fixture):
    def test_retire_refuses_without_ruling(self):
        wn.apply_notice("wiki/sources/srcq.md",
                        "source-integrity-questioned",
                        reason="x", root=self.root)
        page = self.root / "wiki/sources/srcq.md"
        before = page.read_text()
        with self.assertRaises(wn.NoticeError):
            wn.retire_notice("wiki/sources/srcq.md",
                             "source-integrity-questioned",
                             ruling=None, root=self.root)
        with self.assertRaises(wn.NoticeError):
            wn.retire_notice("wiki/sources/srcq.md",
                             "source-integrity-questioned",
                             ruling="  ", root=self.root)
        self.assertEqual(page.read_text(), before)
        # and via the CLI: exit 1, nothing changes
        self.assertEqual(wn.main(
            ["--root", str(self.root), "retire",
             "wiki/sources/srcq.md",
             "source-integrity-questioned"]), 1)
        self.assertEqual(page.read_text(), before)

    def test_retire_with_ruling(self):
        wn.apply_notice("wiki/sources/srcq.md",
                        "source-integrity-questioned",
                        reason="x", root=self.root)
        wn.retire_notice("wiki/sources/srcq.md",
                         "source-integrity-questioned",
                         ruling="owner ruling 2030-10-20, chat",
                         root=self.root)
        text = (self.root / "wiki/sources/srcq.md").read_text()
        self.assertNotIn("notice:begin", text)
        self.assertIn("notice:retired "
                      "id=source-integrity-questioned", text)
        self.assertIn("owner ruling 2030-10-20, chat", text)
        self.assertEqual(wn.list_notices(self.root), [])
        events = wn.load_register(self.root)
        self.assertEqual([e["kind"] for e in events
                          if e["kind"] != "header"],
                         ["applied", "retired"])


class SuggestTests(Fixture):
    def test_mechanical_rules(self):
        cand = wn.suggest(self.root)
        n1 = {r for r, _ in cand["source-integrity-questioned"]}
        self.assertIn("wiki/sources/srcq.md", n1)       # graded
        self.assertIn("wiki/concepts/fromq.md", n1)     # compiled
        n2 = {r for r, _ in cand["claim-negative-treatment"]}
        self.assertIn("wiki/syntheses/neg.md", n2)
        n5 = {r for r, _ in cand["attribution-incomplete"]}
        self.assertIn("wiki/syntheses/bare.md", n5)
        self.assertNotIn("wiki/sources/srcq.md", n5)


class TierTests(Fixture):
    def test_composition(self):
        r = wn.evaluate_tiers("agent1", self.root)
        self.assertTrue(r["admitted"])
        self.assertTrue(r["gateway_token_issued"])
        self.assertTrue(r["verdicts"]["wiki:read"])
        self.assertTrue(r["verdicts"]["wiki:publish"])
        self.assertFalse(r["verdicts"]["wiki:admin"])

    def test_seat_without_token_denies_gateway(self):
        r = wn.evaluate_tiers("filer1", self.root)
        self.assertTrue(r["admitted"])           # the seat
        self.assertTrue(r["branch_channel"])
        self.assertFalse(r["gateway_token_issued"])
        self.assertFalse(any(r["verdicts"].values()))

    def test_unadmitted_denies_all(self):
        r = wn.evaluate_tiers("stranger", self.root)
        self.assertFalse(r["admitted"])
        self.assertFalse(any(r["verdicts"].values()))


class RulesPageTests(unittest.TestCase):
    def test_rules_page_quotes_fixed_text_verbatim(self):
        root = SCRIPTS.parent
        page = (root / "wiki" / "rules" / "notices.md") \
            .read_text(encoding="utf-8")
        for notice in wn.load_vocab(root).values():
            self.assertIn(notice["fixed_text"], page,
                          notice["id"])


if __name__ == "__main__":
    unittest.main()
