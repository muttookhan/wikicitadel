#!/usr/bin/env python3
"""Tests for scripts/wiki_linked_data.py (build wave 6,
item W6: RDF / JSON-LD linked-data export of the wiki
graph).

Pins, on a FIXTURE corpus in a temp dir (the door scripts
copied in, house pattern from test_wiki_edge_labels.py):

  - the JSON-LD expands under its own embedded context
    without errors and carries exactly the model's
    triples; the Turtle parses back to the same set;
    every emitted node carries a type;
  - edge fidelity: the W1.8 label + confidence of an edge
    survive the round trip in BOTH serialisations —
    including an AMBIGUOUS conflicting pair at 0.5;
  - the direct-triple mapping: relation predicates and
    their declared inverses, page->source cito:cites,
    claims joined from the register + frontmatter,
    citations with their oa:TextQuoteSelector;
  - the loss report: an unmapped frontmatter field and
    an unmapped relation are named with counts; mapped
    constructs never appear in it;
  - citation target identity: a `sources:` entry naming
    a wiki page joins the page node (no phantom source);
  - determinism: two exports byte-identical; the corpus
    tree's bytes unchanged by an export.

Plus one real-corpus test: the validity gate passes over
the live tree (counts pinned loosely — the corpus grows).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LD = load_module("wiki_linked_data_under_test",
                 SCRIPTS / "wiki_linked_data.py")
WK = LD.NS["wk"]
CITO = LD.NS["cito"]
OA = LD.NS["oa"]


def I(path):
    return LD.iri(path)


ALPHA = """---
title: Alpha
type: entity
created: 2026-10-20
updated: 2026-10-21
tags:
  - test-tag
sources:
  - raw/sources/note.md
links:
  grounds: [wiki/concepts/beta.md]
  exemplifies: [wiki/concepts/beta.md]
claim: Alpha stands as stated.
as_of: 2026-10-21
zeta_custom: unmapped-value
---

# Alpha

Alpha rests on [[beta]].
"""

BETA = """---
title: Beta
type: concept
created: 2026-10-20
updated: 2026-10-20
tags:
  - test-tag
links:
  supersedes: [wiki/concepts/gamma.md]
  extends: [wiki/concepts/gamma.md]
---

# Beta

Beta builds on [[alpha]].
"""

GAMMA = """---
title: Gamma
type: synthesis
created: 2026-10-19
updated: 2026-10-19
---

# Gamma

The older account.
"""

CLAIM_ROW = {
    "claim_id": "wiki/entities/alpha.md",
    "text": "Alpha stands as stated.",
    "stated": "2026-10-21", "supports": 1, "contradicts": 0,
    "verified_n": 0, "superseded": False,
    "indexed_on": "2026-10-22", "hash": "0123456789abcdef",
}

LOCKFILE = {"citations": [{
    "id": "c0001", "page": "wiki/entities/alpha.md",
    "page_line": 14, "claim": "Alpha stands as stated.",
    "claim_hash": "aaaa", "source": "raw/sources/note.md",
    "range": [1, 2], "line_hashes": ["bb", "cc"],
    "content_hash": "dd",
    "selector": {"type": "TextQuoteSelector",
                 "exact": "Alpha rests", "prefix": "pre ",
                 "suffix": " post"},
}]}

TAG_REGISTRY = [
    {"kind": "header", "register": "tag-registry"},
    {"kind": "concept", "id": "test-tag",
     "prefLabel": "test-tag", "altLabels": [],
     "scopeNote": "A fixture tag.", "broader": [],
     "status": "preferred"},
]


def make_root(base):
    root = Path(base) / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "tools" / "lens").mkdir(parents=True)
    for name in ("wiki_validate.py", "wiki_traverse.py",
                 "wiki_edge_labels.py", "wiki_linked_data.py"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                root / "tools" / "lens" / "lenslib.py")
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "raw" / "sources").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    (root / "wiki" / "entities" / "alpha.md").write_text(
        ALPHA, encoding="utf-8")
    (root / "wiki" / "concepts" / "beta.md").write_text(
        BETA, encoding="utf-8")
    (root / "wiki" / "concepts" / "gamma.md").write_text(
        GAMMA, encoding="utf-8")
    (root / "raw" / "sources" / "note.md").write_text(
        "line one\nline two\n", encoding="utf-8")
    (root / "evaluation" / "claim-index.jsonl").write_text(
        json.dumps(CLAIM_ROW) + "\n", encoding="utf-8")
    (root / "evaluation"
     / "citation-lockfile.json").write_text(
        json.dumps(LOCKFILE), encoding="utf-8")
    (root / "evaluation" / "tag-registry.jsonl").write_text(
        "\n".join(json.dumps(r) for r in TAG_REGISTRY) + "\n",
        encoding="utf-8")
    return root


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def assertion(T, subj, obj, relation):
    """The assertion node in T linking subj->obj under
    `relation`, as {predicate: object}."""
    for (s, p, o) in T:
        if p == WK + "edgeSubject" and o == ("iri", subj):
            pass
    nodes = {s for (s, p, o) in T
             if p == WK + "edgeSubject" and o == ("iri", subj)}
    for n in nodes:
        props = {}
        for (s, p, o) in T:
            if s == n:
                props[p] = o
        if props.get(WK + "edgeObject") == ("iri", obj) \
                and props.get(WK + "relation") == \
                ("lit", relation, None):
            return props
    return None


class FixtureExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = make_root(self.tmp)
        self.T, self.counts, self.loss, self.extras = \
            LD.build_triples(self.root)

    def test_validity_gate(self):
        self.assertEqual(LD.check_triples(self.T), [])

    def test_jsonld_round_trip(self):
        doc = LD.render_jsonld(self.T)
        self.assertEqual(LD.expand_jsonld(doc), self.T)

    def test_turtle_round_trip(self):
        self.assertEqual(
            LD.parse_turtle(LD.render_turtle(self.T)), self.T)

    def test_every_node_typed(self):
        typed = {s for (s, p, _o) in self.T
                 if p == LD.RDF_TYPE}
        subjects = {s for (s, _p, _o) in self.T}
        self.assertEqual(subjects - typed, set())

    def test_ambiguous_pair_label_round_trip(self):
        beta, gamma = I("wiki/concepts/beta.md"), \
            I("wiki/concepts/gamma.md")
        for triples in (self.T,
                        LD.parse_turtle(
                            LD.render_turtle(self.T)),
                        LD.expand_jsonld(
                            LD.render_jsonld(self.T))):
            props = assertion(triples, beta, gamma,
                              "supersedes")
            self.assertIsNotNone(props)
            self.assertEqual(props[WK + "provenanceLabel"],
                             ("lit", "AMBIGUOUS", None))
            self.assertEqual(props[WK + "edgeConfidence"],
                             ("lit", "0.5",
                              LD.NS["xsd"] + "decimal"))

    def test_extracted_citation_label(self):
        props = assertion(self.T, I("wiki/entities/alpha.md"),
                          I("raw/sources/note.md"), "cites")
        self.assertIsNotNone(props)
        self.assertEqual(props[WK + "provenanceLabel"],
                         ("lit", "EXTRACTED", None))
        self.assertEqual(props[WK + "edgeConfidence"],
                         ("lit", "1.0", LD.NS["xsd"] + "decimal"))

    def test_direct_triples_and_inverses(self):
        alpha, beta = I("wiki/entities/alpha.md"), \
            I("wiki/concepts/beta.md")
        self.assertIn((alpha, WK + "grounds",
                       ("iri", beta)), self.T)
        self.assertIn((beta, WK + "isGroundedBy",
                       ("iri", alpha)), self.T)
        self.assertIn((alpha, CITO + "cites",
                       ("iri", I("raw/sources/note.md"))),
                      self.T)
        beta_node = [o for (s, p, o) in self.T
                     if s == beta and p == LD.RDF_TYPE]
        self.assertIn(("iri", LD.NS["skos"] + "Concept"),
                      beta_node)

    def test_claim_and_citation_nodes(self):
        claim = I("claim/wiki/entities/alpha.md")
        self.assertIn((claim, LD.RDF_TYPE,
                       ("iri", WK + "Claim")), self.T)
        self.assertIn((claim, WK + "registerHash",
                       ("lit", "0123456789abcdef", None)),
                      self.T)
        self.assertIn((claim, WK + "claimText",
                       ("lit", "Alpha stands as stated.",
                        None)), self.T)
        cit = I("citation/c0001")
        self.assertIn((cit, CITO + "cites",
                       ("iri", I("raw/sources/note.md"))),
                      self.T)
        sel = cit + "/selector"
        self.assertIn((sel, LD.RDF_TYPE,
                       ("iri", OA + "TextQuoteSelector")),
                      self.T)
        self.assertIn((sel, OA + "exact",
                       ("lit", "Alpha rests", None)), self.T)

    def test_loss_report(self):
        rows = {(r["kind"], r["construct"]): r["count"]
                for r in self.loss.as_list()}
        self.assertEqual(
            rows[("frontmatter-field",
                  "frontmatter field 'zeta_custom'")], 1)
        self.assertEqual(
            rows[("relation", "relation 'exemplifies'")], 1)
        for _kind, construct in rows:
            self.assertNotIn("grounds", construct)
            self.assertNotIn("title", construct)

    def test_page_target_citation_joins_page(self):
        # alpha cites beta via its body too; the assertion
        # for the mentions edge points at the page node,
        # and no phantom raw/ source exists for it.
        self.assertFalse(any(
            s == I("raw/wiki/concepts/beta.md")
            for (s, _p, _o) in self.T))

    def test_export_determinism_and_untouched_corpus(self):
        before = tree_digest(self.root)
        out1, out2 = self.tmp / "out1", self.tmp / "out2"
        r1, problems = LD.export(self.root, out1)
        self.assertEqual(problems, [])
        r2, _ = LD.export(self.root, out2)
        for name in ("wiki.jsonld", "wiki.ttl",
                     "context.jsonld", "llms.txt",
                     "linked-data-report.json"):
            self.assertEqual((out1 / name).read_bytes(),
                             (out2 / name).read_bytes(), name)
        self.assertEqual(tree_digest(self.root), before)
        self.assertEqual(r1["counts"]["pages"], 3)
        self.assertEqual(r1["counts"]["claims"], 1)
        self.assertEqual(r1["counts"]["citations"], 1)
        canon = LD.render_ntriples(self.T)
        self.assertEqual(
            r1["canonical_sha256"],
            hashlib.sha256(canon.encode()).hexdigest())


class RealCorpusTests(unittest.TestCase):
    def test_real_corpus_gate(self):
        T, counts, loss, _extras = LD.build_triples(REPO)
        self.assertEqual(LD.check_triples(T), [])
        self.assertGreaterEqual(counts["pages"], 40)
        self.assertGreaterEqual(counts["citations"], 10)
        for row in loss.as_list():
            self.assertTrue(row["construct"])


if __name__ == "__main__":
    unittest.main()
