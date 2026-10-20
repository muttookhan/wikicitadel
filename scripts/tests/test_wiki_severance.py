#!/usr/bin/env python3
"""Retrieval severance (item 20): the generator and its matching
rules.

The generator (scripts/wiki_severance.py) derives
evaluation/retrieval-severance.json from the decisions register,
the treatment register (negative standings only) and the wiki's
frontmatter supersession signals. These tests pin: the
derivation from fixture registers (including standing-grade
folding — a later questioned event does not un-sever a negative
subject), the register-line citations, byte determinism, the
staleness check, and the TEXT/QUERY matching thresholds the
consumers share.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wiki_severance", ROOT / "scripts" / "wiki_severance.py")
sev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sev)


DECISIONS = [
    {"kind": "header", "register": "decisions-register"},
    {"kind": "decision", "id": "d1", "title": "A seat",
     "source": {"page": "wiki/syntheses/decisions.md"},
     "current_form": "The seat is open.",
     "superseded_forms": [{
         "form_id": "d1-old", "title": "The seat stays SHUT",
         "superseded_on": "2030-10-16",
         "match_phrases": ["seat stays shut", "seat shut"]}]},
    {"kind": "decision", "id": "d2", "title": "No forms",
     "source": {"page": "wiki/syntheses/decisions.md"},
     "current_form": "Standing.", "superseded_forms": []},
]

TREATMENTS = [
    {"kind": "header", "register": "treatment-register"},
    {"kind": "treatment", "id": "treat-0001", "date": "2030-10-18",
     "subject": {"page": "wiki/sources/a.md",
                 "claim": "the bridge toll is forty dollars exactly"},
     "grade": "negative"},
    {"kind": "treatment", "id": "treat-0002", "date": "2030-10-18",
     "subject": {"page": "wiki/sources/b.md",
                 "claim": "a merely doubted claim about rainfall"},
     "grade": "questioned"},
    # Same subject: questioned first, negative later -> negative.
    {"kind": "treatment", "id": "treat-0003", "date": "2030-10-18",
     "subject": {"page": "wiki/sources/c.md",
                 "claim": "the vault holds ninety ledgers total"},
     "grade": "questioned"},
    {"kind": "treatment", "id": "treat-0004", "date": "2030-10-19",
     "subject": {"page": "wiki/sources/c.md",
                 "claim": "the vault holds ninety ledgers total"},
     "grade": "negative"},
    # Negative first, questioned later -> standing stays negative
    # (the strongest signal governs, citator practice).
    {"kind": "treatment", "id": "treat-0005", "date": "2030-10-18",
     "subject": {"page": "wiki/sources/d.md",
                 "claim": "harbour fees are waived for members"},
     "grade": "negative"},
    {"kind": "treatment", "id": "treat-0006", "date": "2030-10-19",
     "subject": {"page": "wiki/sources/d.md",
                 "claim": "harbour fees are waived for members"},
     "grade": "questioned"},
]

# A stand-in for scripts/wiki_treatment.py in the fixture root:
# page_entries() consumes superseded_pages() + observe only, and
# the Lane-2 signal computation is wiki_treatment's own tested
# domain — the stub reproduces its interface over frontmatter.
TREATMENT_STUB = '''
import re

class _Obs:
    @staticmethod
    def parse_frontmatter(text):
        m = re.match(r"\\A---\\n(.*?)\\n---\\n?", text, re.S)
        if not m:
            return {}, text
        fields = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip().strip("\\"")
        return fields, text[m.end():]

observe = _Obs()

def superseded_pages(root):
    out = {}
    wiki = root / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            fields, _b = observe.parse_frontmatter(
                p.read_text(encoding="utf-8"))
            if str(fields.get("status", "")).lower() in (
                    "superseded", "deprecated"):
                out[p.relative_to(root).as_posix()] = (
                    "status: " + fields["status"])
    return out
'''


def write_fixture(root: Path):
    (root / "evaluation").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "wiki" / "syntheses").mkdir(parents=True)
    (root / "evaluation" / "decisions-register.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in DECISIONS),
        encoding="utf-8")
    (root / "evaluation" / "treatment-register.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in TREATMENTS),
        encoding="utf-8")
    (root / "scripts" / "wiki_treatment.py").write_text(
        TREATMENT_STUB, encoding="utf-8")
    (root / "wiki" / "sources" / "old.md").write_text(
        "---\ntitle: \"Old page\"\nstatus: superseded\n---\n\n"
        "# Old page\n\nSuperseded content.\n", encoding="utf-8")
    (root / "wiki" / "sources" / "live.md").write_text(
        "---\ntitle: \"Live page\"\nstatus: active\n---\n\n"
        "# Live page\n\nCurrent content.\n", encoding="utf-8")


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_fixture(self.root)
        self.artefact = sev.build_artefact(self.root)
        self.by_kind = {}
        for e in self.artefact["entries"]:
            self.by_kind.setdefault(e["kind"], []).append(e)

    def tearDown(self):
        self._tmp.cleanup()

    def test_entry_kinds_and_counts(self):
        self.assertEqual(len(self.by_kind["decision-form"]), 1)
        # a (negative), c (questioned->negative), d (negative->
        # questioned, standing still negative); b never severs.
        self.assertEqual(len(self.by_kind["treatment"]), 3)
        self.assertEqual(len(self.by_kind["page"]), 1)

    def test_register_line_citations(self):
        form = self.by_kind["decision-form"][0]
        self.assertEqual(form["source"]["register"],
                         "evaluation/decisions-register.jsonl")
        self.assertEqual(form["source"]["line"], 2)
        self.assertEqual(form["source"]["record_id"], "d1-old")
        self.assertEqual(form["page"], "wiki/syntheses/decisions.md")
        treat = {e["source"]["record_id"]: e
                 for e in self.by_kind["treatment"]}
        self.assertEqual(treat["treat-0001"]["source"]["line"], 2)
        # c's severing line is the NEGATIVE event, not the first.
        self.assertEqual(treat["treat-0004"]["source"]["line"], 5)

    def test_questioned_only_subject_absent(self):
        pages = {e["page"] for e in self.by_kind["treatment"]}
        self.assertNotIn("wiki/sources/b.md", pages)

    def test_page_entry_shape(self):
        page = self.by_kind["page"][0]
        self.assertEqual(page["page"], "wiki/sources/old.md")
        self.assertIsNone(page["claim"])
        self.assertEqual(page["source"]["signal"],
                         "status: superseded")

    def test_form_cues(self):
        form = self.by_kind["decision-form"][0]
        self.assertIn(["seat", "stays", "shut"],
                      form["cues"]["phrases"])
        self.assertIn(["seat", "shut"], form["cues"]["phrases"])
        # The form's title joins the phrases too.
        self.assertIn(["the", "seat", "stays", "shut"],
                      form["cues"]["phrases"])
        self.assertEqual(form["cues"]["terms"],
                         ["seat", "shut", "stays"])

    def test_deterministic_bytes(self):
        again = sev.build_artefact(self.root)
        self.assertEqual(sev.render_artefact(self.artefact),
                         sev.render_artefact(again))

    def test_ids_assigned_in_sorted_order(self):
        ids = [e["id"] for e in self.artefact["entries"]]
        self.assertEqual(ids, [f"sev-{i:04d}"
                               for i in range(1, len(ids) + 1)])
        keys = [(e["kind"], e["page"]) for e in self.artefact["entries"]]
        self.assertEqual(keys, sorted(keys))


class MatchingTests(unittest.TestCase):
    def entry(self, phrases=(), terms=()):
        return {"cues": {"phrases": [list(p) for p in phrases],
                         "terms": list(terms)}}

    def test_phrase_hit_must_be_contiguous(self):
        toks = ["the", "seat", "stays", "shut", "today"]
        self.assertTrue(sev.phrase_hit(toks, ["seat", "stays", "shut"]))
        self.assertFalse(sev.phrase_hit(toks, ["seat", "shut"]))
        self.assertFalse(sev.phrase_hit(toks, []))

    def test_text_match_term_threshold_is_four_fifths(self):
        e = self.entry(terms=["alpha", "bravo", "charlie", "delta",
                              "echo"])
        self.assertTrue(sev.text_matches(
            ["alpha", "bravo", "charlie", "delta"], e))       # 4/5
        self.assertFalse(sev.text_matches(
            ["alpha", "bravo", "charlie"], e))                # 3/5

    def test_query_match_term_threshold_is_half_min_three(self):
        e = self.entry(terms=["alpha", "bravo", "charlie", "delta",
                              "echo", "foxtrot"])
        self.assertTrue(sev.query_matches(
            ["alpha", "bravo", "charlie"], e))                # 3 of 6
        self.assertFalse(sev.query_matches(["alpha", "bravo"], e))
        big = self.entry(terms=[f"t{i:02d}" for i in range(13)])
        self.assertFalse(sev.query_matches(
            [f"t{i:02d}" for i in range(6)], big))            # 6 < 7
        self.assertTrue(sev.query_matches(
            [f"t{i:02d}" for i in range(7)], big))            # 7 of 13

    def test_distinctive_terms_drop_stopwords_and_short(self):
        self.assertEqual(
            sev.distinctive_terms("The seat is on a mat, stays put"),
            ["mat", "put", "seat", "stays"])


if __name__ == "__main__":
    unittest.main()
