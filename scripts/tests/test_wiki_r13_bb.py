"""Tests for R13 BB: CJK normalise, Kiwi trial, ontology,
annotation contract, link embedding eval."""
import importlib.util, json, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    s = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


CJK = load("wiki_cjk_normalise")
KIWI = load("wiki_kiwi_trial")
ONTO = load("wiki_ontology_check")
ANN = load("wiki_annotation_contract")
LINK = load("wiki_link_embedding_eval")


class CjkT(unittest.TestCase):
    def test_autospace_inserted(self):
        out, f = CJK.process("使用Python编程")
        self.assertEqual(out, "使用 Python 编程")
        self.assertTrue(any(r == "cjk-autospace" for r, _ in f))

    def test_code_untouched(self):
        src = "```\n使用Python\n```\n正文`code中文`结束"
        out, _ = CJK.process(src)
        self.assertIn("使用Python", out)
        self.assertIn("`code中文`", out)

    def test_halfwidth_punct_fullwidth_in_cjk(self):
        out, _ = CJK.process("你好,世界.")
        self.assertEqual(out, "你好，世界。")

    def test_latin_punct_kept(self):
        out, _ = CJK.process("Hello, world.")
        self.assertEqual(out, "Hello, world.")

    def test_fullwidth_alnum(self):
        out, _ = CJK.process("Ｐｙｔｈｏｎ３")
        self.assertEqual(out, "Python3")

    def test_space_around_fullwidth_punct_removed(self):
        out, _ = CJK.process("你好 ， 世界")
        self.assertEqual(out, "你好，世界")

    def test_rules_register_honest(self):
        rules = json.loads((SCRIPTS.parent / "evaluation" /
                            "cjk-normalisation-rules.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(rules["licence"].split()[0], "MIT")
        typo = [r for r in rules["rules"]
                if r["id"] == "cjk-fix-term-typo"][0]
        self.assertFalse(typo["applied"])


class KiwiT(unittest.TestCase):
    def test_missing_python_is_door_failure(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / "ev.json"
            sample = Path(td) / "s.txt"
            sample.write_text("한국어", encoding="utf-8")
            rc = KIWI.main(["run", "--sample", str(sample),
                            "--evidence", str(ev),
                            "--python", "/nonexistent/python"])
            self.assertEqual(rc, 2)
            data = json.loads(ev.read_text())
            self.assertFalse(data["ran"])
            self.assertIn("door_failure", data)

    def test_runner_uses_tokenize(self):
        self.assertIn("tokenize", KIWI.RUNNER)
        self.assertIn("split_into_sents", KIWI.RUNNER)


GOOD_TERM = """---
title: "Test term"
type: ontology-term
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: []
term_id: "test-term"
preferred_label: "Test term"
status: accepted
---

# Test term

## Definition

A term.

## Relations

- broader: [[other-term]]

## Revision history

- 2026-10-21: term proposed (tester)

## Discussion

None open.
"""


class OntoT(unittest.TestCase):
    def setUp(self):
        self.contract = ONTO.load_contract(
            SCRIPTS.parent / "evaluation" /
            "ontology-page-contract.json")

    def test_good_term_clean(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test-term.md"
            p.write_text(GOOD_TERM, encoding="utf-8")
            errs, _n, _fm = ONTO.check_page(p, self.contract)
            self.assertEqual(errs, [])

    def test_bad_predicate_and_missing_discussion(self):
        bad = GOOD_TERM.replace("- broader:", "- owns:") \
                       .replace("## Discussion", "## Notes")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.md"
            p.write_text(bad, encoding="utf-8")
            errs, _n, _fm = ONTO.check_page(p, self.contract)
            self.assertTrue(any("predicate" in e for e in errs))
            self.assertTrue(any("Discussion" in e for e in errs))

    def test_bad_status(self):
        bad = GOOD_TERM.replace("status: accepted", "status: maybe")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.md"
            p.write_text(bad, encoding="utf-8")
            errs, _n, _fm = ONTO.check_page(p, self.contract)
            self.assertTrue(any("status" in e for e in errs))


def rec(**kw):
    base = {"page": "wiki/golden.md", "span_start": 0, "span_end": 4,
            "surface": "test", "label": "PERSON", "state": "accepted",
            "annotator": "owner", "kb_target": "wiki/entities/x.md"}
    base.update(kw)
    return base


class AnnT(unittest.TestCase):
    def setUp(self):
        self.contract = ANN.load_contract(
            SCRIPTS.parent / "evaluation" / "annotation-contract.json")

    def test_valid_record(self):
        self.assertEqual(ANN.validate([rec()], self.contract), [])

    def test_adjudicated_needs_adjudicator(self):
        errs = ANN.validate([rec(state="adjudicated")], self.contract)
        self.assertTrue(any("adjudicat" in e for e in errs))

    def test_unlinked_needs_reason(self):
        r = rec()
        del r["kb_target"]
        errs = ANN.validate([r], self.contract)
        self.assertTrue(any("kb_unlinked_reason" in e for e in errs))

    def test_kappa_perfect_and_chance(self):
        self.assertEqual(ANN.cohens_kappa(
            [("A", "A"), ("B", "B"), ("A", "A")]), 1.0)
        k = ANN.cohens_kappa([("A", "B"), ("B", "A"),
                              ("A", "A"), ("B", "B")])
        self.assertAlmostEqual(k, 0.0, places=6)

    def test_agreement_counts(self):
        recs = [rec(annotator="a1"), rec(annotator="a2"),
                rec(annotator="a1", span_start=10, span_end=12)]
        rep = ANN.agreement(recs)
        self.assertEqual(rep["units_double_annotated"], 1)
        self.assertEqual(rep["units_single_annotated"], 1)

    def test_seeded_register_header_only(self):
        records, errors = ANN.load_records(
            SCRIPTS.parent / "evaluation" / "annotation-agreement.jsonl")
        self.assertEqual(records, [])
        self.assertEqual(errors, [])


class LinkT(unittest.TestCase):
    def _graph(self, td):
        w = Path(td)
        (w / "a.md").write_text("[[b]] [[c]]", encoding="utf-8")
        (w / "b.md").write_text("[[a]] [[c]]", encoding="utf-8")
        (w / "c.md").write_text("[[a]] [[b]]", encoding="utf-8")
        (w / "d.md").write_text("[[a]]", encoding="utf-8")
        return LINK.build_graph(w)

    def test_graph(self):
        with tempfile.TemporaryDirectory() as td:
            g = self._graph(td)
            self.assertEqual(g["a"], {"b", "c"})
            self.assertEqual(g["d"], {"a"})

    def test_evaluate_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            g = self._graph(td)
            r1 = LINK.evaluate(g)
            r2 = LINK.evaluate(g)
            self.assertEqual(r1, r2)
            self.assertGreaterEqual(r1["hits_at_10"], 0.0)
            self.assertLessEqual(r1["hits_at_10"], 1.0)
            self.assertGreater(r1["held_out"], 0)

    def test_suggestions_never_self_or_existing(self):
        with tempfile.TemporaryDirectory() as td:
            g = self._graph(td)
            for s in LINK.suggestions(g):
                self.assertNotEqual(s["source"], s["candidate"])
                self.assertNotIn(s["candidate"], g[s["source"]])


if __name__ == "__main__":
    unittest.main()
