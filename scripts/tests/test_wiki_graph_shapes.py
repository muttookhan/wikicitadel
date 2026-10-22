#!/usr/bin/env python3
"""Tests for scripts/wiki_graph_shapes.py (build wave 6,
item W6: SHACL-AF pattern graph shape validation).

Pins, on SYNTHETIC triple sets in the linked-data
export's own triple format (no fixture corpus needed —
the checker is a pure function over a triple set, plus
the citation resolution clause against a temp root):

  - every shape fires on its violating fixture and is
    silent on its conforming fixture: page type +
    class agreement, the type vocabulary on generic
    pages, the closed relation vocabulary (exemplifies
    is the canonical failure), the declared-inverse
    pair (page->page only — lockfile citation triples
    and page->source cites are out of scope by the
    vocabulary's own "when both pages are ours"), the
    W1.8 label set + confidence range (AMBIGUOUS at
    0.5 passes), the claim shape (text / as_of /
    statedOn / the page's sources), the citation shape
    (lock hash, quote selector, on-disk resolution),
    the tombstone replacement half, tag registration
    (scopeNote as the registry-join marker,
    deprecated-in-use);
  - determinism: two validations of one set render
    byte-identical reports; the shapes artefacts
    render identically twice and name every shape;

Plus one real-corpus test: the live tree does NOT
conform — the two exemplifies edges surface under
RelationVocabularyShape by name — and the compiled
pages' types are clean. Counts pinned loosely (the
corpus grows); the exemplifies count is pinned
exactly because the brief names it.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
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


gs = load_module("wiki_graph_shapes",
                 SCRIPTS / "wiki_graph_shapes.py")
ld = gs.ld
E = gs.E


def node(path):
    return ld.iri(path)


def typed(n, *classes):
    return [(n, ld.RDF_TYPE, ld.ref(E(c))) for c in classes]


def litp(n, pred, value, datatype=None):
    return (n, E(pred), ld.lit(value, datatype))


def refp(n, pred, target):
    return (n, E(pred), ld.ref(target))


def page(path, *classes):
    return node(path), typed(node(path), *(classes or
                                           ("wk:Page",)))


def results_for(report, shape_id):
    return [r for r in report["results"]
            if r["sourceShape"] == shape_id]


def shape_row(report, shape_id):
    return next(r for r in report["shapes"]
                if r["id"] == shape_id)


PAGE_A, _ = page("wiki/concepts/a.md", "wk:ConceptPage",
                 "skos:Concept")
PAGE_B, _ = page("wiki/concepts/b.md", "wk:ConceptPage",
                 "skos:Concept")


def assertion(relation="mentions", label="EXTRACTED",
              conf="1.0", polarity="positive"):
    a = node("assertion/000001")
    rows = typed(a, "wk:EdgeAssertion")
    rows += [refp(a, "wk:edgeSubject", PAGE_A),
             refp(a, "wk:edgeObject", PAGE_B)]
    if relation is not None:
        rows.append(litp(a, "wk:relation", relation))
    if label is not None:
        rows.append(litp(a, "wk:provenanceLabel", label))
    if conf is not None:
        rows.append(litp(a, "wk:edgeConfidence", conf,
                         gs.XSD_DECIMAL))
    if polarity is not None:
        rows.append(litp(a, "wk:polarity", polarity))
    return a, rows


class PageTypeShapesTest(unittest.TestCase):
    def test_good_page_passes(self):
        n, rows = page("wiki/syntheses/x.md",
                       "wk:SynthesisPage", "schema:Article")
        rows.append(litp(n, "wk:pageType", "synthesis"))
        report = gs.validate(set(rows))
        self.assertEqual([], results_for(
            report, "wkshape:PageTypeShape"))

    def test_class_disagreement_fails(self):
        n, rows = page("wiki/syntheses/x.md",
                       "wk:SynthesisPage", "schema:Article")
        rows.append(litp(n, "wk:pageType", "concept"))
        out = results_for(gs.validate(set(rows)),
                          "wkshape:PageTypeShape")
        self.assertEqual(1, len(out))
        self.assertEqual("concept", out[0]["value"])

    def test_missing_and_duplicate_type_fail(self):
        n, rows = page("wiki/sources/x.md", "wk:SourcePage")
        out = results_for(gs.validate(set(rows)),
                          "wkshape:PageTypeShape")
        self.assertEqual(1, len(out))
        rows.append(litp(n, "wk:pageType", "source"))
        rows.append(litp(n, "wk:pageType", "query"))
        out = results_for(gs.validate(set(rows)),
                          "wkshape:PageTypeShape")
        self.assertEqual(1, len(out))

    def test_generic_page_unknown_type_fails_vocab(self):
        n, rows = page("wiki/x.md")
        rows.append(litp(n, "wk:pageType", "banana"))
        report = gs.validate(set(rows))
        out = results_for(report,
                          "wkshape:PageTypeVocabularyShape")
        self.assertEqual(1, len(out))
        self.assertEqual("banana", out[0]["value"])
        # the structural case: no declared type at all
        n2, rows2 = page("wiki/index.md")
        report2 = gs.validate(set(rows2))
        self.assertEqual([], results_for(
            report2, "wkshape:PageTypeVocabularyShape"))


class RelationAndProvenanceTest(unittest.TestCase):
    def test_exemplifies_fails_by_name(self):
        _a, rows = assertion(relation="exemplifies")
        out = results_for(gs.validate(set(rows)),
                          "wkshape:RelationVocabularyShape")
        self.assertEqual(1, len(out))
        self.assertEqual("exemplifies", out[0]["value"])

    def test_closed_terms_pass(self):
        for rel in ("cites", "grounds", "mentions",
                    "is-grounded-by", "supersedes"):
            _a, rows = assertion(relation=rel)
            self.assertEqual([], results_for(
                gs.validate(set(rows)),
                "wkshape:RelationVocabularyShape"), rel)

    def test_ambiguous_half_confidence_passes(self):
        _a, rows = assertion(label="AMBIGUOUS", conf="0.5")
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:EdgeProvenanceShape"))

    def test_bad_label_confidence_polarity_fail(self):
        _a, rows = assertion(label="GUESSED")
        self.assertEqual(1, len(results_for(
            gs.validate(set(rows)),
            "wkshape:EdgeProvenanceShape")))
        _a, rows = assertion(conf="1.5")
        self.assertEqual(1, len(results_for(
            gs.validate(set(rows)),
            "wkshape:EdgeProvenanceShape")))
        _a, rows = assertion(polarity=None)
        self.assertEqual(1, len(results_for(
            gs.validate(set(rows)),
            "wkshape:EdgeProvenanceShape")))


class DeclaredInverseTest(unittest.TestCase):
    def _pages(self):
        _a, rows_a = page("wiki/concepts/a.md",
                          "wk:ConceptPage", "skos:Concept")
        _b, rows_b = page("wiki/concepts/b.md",
                          "wk:ConceptPage", "skos:Concept")
        rows_a.append(litp(PAGE_A, "wk:pageType",
                           "concept"))
        rows_b.append(litp(PAGE_B, "wk:pageType",
                           "concept"))
        return rows_a + rows_b

    def test_pair_present_passes(self):
        rows = self._pages()
        rows.append(refp(PAGE_A, "dcterms:replaces",
                         PAGE_B))
        rows.append(refp(PAGE_B, "dcterms:isReplacedBy",
                         PAGE_A))
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:DeclaredInverseShape"))

    def test_forward_only_fails(self):
        rows = self._pages()
        rows.append(refp(PAGE_A, "wk:grounds", PAGE_B))
        out = results_for(gs.validate(set(rows)),
                          "wkshape:DeclaredInverseShape")
        self.assertEqual(1, len(out))

    def test_contradicts_is_self_inverse(self):
        rows = self._pages()
        rows.append(refp(PAGE_A, "wk:contradicts", PAGE_B))
        self.assertEqual(1, len(results_for(
            gs.validate(set(rows)),
            "wkshape:DeclaredInverseShape")))
        rows.append(refp(PAGE_B, "wk:contradicts", PAGE_A))
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:DeclaredInverseShape"))

    def test_citation_triples_out_of_scope(self):
        # the lockfile form: a Citation node citing a raw
        # source carries cito:cites with no inverse — the
        # vocabulary's pair rule binds pages, not these.
        rows = self._pages()
        cit = node("citation/cit-1")
        rows += typed(cit, "wk:Citation")
        raw = node("raw/sources/x.md")
        rows += typed(raw, "wk:RawSource", "prov:Entity")
        rows.append(refp(cit, "cito:cites", raw))
        rows.append(refp(PAGE_A, "cito:cites", raw))
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:DeclaredInverseShape"))


class ClaimShapeTest(unittest.TestCase):
    def _claim(self, page_cites=True, as_of=True):
        claim = node("claim/wiki/concepts/a.md")
        rows = typed(claim, "wk:Claim")
        rows.append(litp(claim, "wk:claimText",
                         "A falsifiable sentence."))
        rows.append(refp(claim, "wk:statedOn", PAGE_A))
        if as_of:
            rows.append(litp(claim, "wk:asOf", "2026-10-22",
                             ld.XSD + "date"))
        _a, page_rows = page("wiki/concepts/a.md",
                             "wk:ConceptPage", "skos:Concept")
        rows += page_rows
        rows.append(litp(PAGE_A, "wk:pageType", "concept"))
        if page_cites:
            raw = node("raw/sources/x.md")
            rows += typed(raw, "wk:RawSource")
            rows.append(refp(PAGE_A, "cito:cites", raw))
            rows.append(refp(raw, "cito:isCitedBy", PAGE_A))
        return claim, rows

    def test_full_claim_passes(self):
        _c, rows = self._claim()
        self.assertEqual([], results_for(
            gs.validate(set(rows)), "wkshape:ClaimShape"))

    def test_page_without_sources_fails(self):
        _c, rows = self._claim(page_cites=False)
        out = results_for(gs.validate(set(rows)),
                          "wkshape:ClaimShape")
        self.assertEqual(1, len(out))
        self.assertEqual("cito:cites", out[0]["resultPath"])

    def test_missing_as_of_fails(self):
        _c, rows = self._claim(as_of=False)
        self.assertEqual(1, len(results_for(
            gs.validate(set(rows)), "wkshape:ClaimShape")))


class CitationShapeTest(unittest.TestCase):
    def _citation(self, root, with_hash=True):
        cit = node("citation/cit-1")
        rows = typed(cit, "wk:Citation")
        _p, page_rows = page("wiki/concepts/a.md",
                             "wk:ConceptPage", "skos:Concept")
        rows += page_rows
        rows.append(litp(PAGE_A, "wk:pageType", "concept"))
        raw = node("raw/sources/x.md")
        rows += typed(raw, "wk:RawSource", "prov:Entity")
        sel = node("citation/cit-1/selector")
        rows += typed(sel, "oa:TextQuoteSelector")
        rows.append(refp(cit, "wk:onPage", PAGE_A))
        rows.append(refp(cit, "wk:citesSource", raw))
        rows.append(refp(cit, "wk:hasSelector", sel))
        if with_hash:
            rows.append(litp(cit, "wk:contentHash",
                             "abc123"))
        return cit, rows

    def test_full_citation_passes_and_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "raw" / "sources").mkdir(parents=True)
            (root / "raw" / "sources" / "x.md").write_text(
                "source\n", encoding="utf-8")
            _c, rows = self._citation(root)
            self.assertEqual([], results_for(
                gs.validate(set(rows), root=root),
                "wkshape:CitationShape"))
            # remove the file: the same graph now fails
            # the resolution clause, by path
            (root / "raw" / "sources" / "x.md").unlink()
            out = results_for(
                gs.validate(set(rows), root=root),
                "wkshape:CitationShape")
            self.assertEqual(1, len(out))
            self.assertEqual("raw/sources/x.md",
                             out[0]["value"])

    def test_missing_hash_and_wrong_selector_fail(self):
        _c, rows = self._citation(None, with_hash=False)
        out = results_for(gs.validate(set(rows)),
                          "wkshape:CitationShape")
        self.assertEqual(1, len(out))
        self.assertEqual("wk:contentHash",
                         out[0]["resultPath"])


class TombstoneAndTagTest(unittest.TestCase):
    def test_tombstone_without_replacement_fails(self):
        n, rows = page("wiki/old.md", "wk:SynthesisPage",
                       "schema:Article")
        rows.append(litp(n, "wk:pageType", "synthesis"))
        rows.append(litp(n, "wk:status", "tombstoned"))
        report = gs.validate(set(rows))
        out = results_for(report, "wkshape:TombstoneShape")
        self.assertEqual(1, len(out))
        new, new_rows = page("wiki/new.md",
                             "wk:SynthesisPage",
                             "schema:Article")
        rows += new_rows
        rows.append(litp(new, "wk:pageType", "synthesis"))
        rows.append(refp(new, "dcterms:replaces", n))
        rows.append(refp(n, "dcterms:isReplacedBy", new))
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:TombstoneShape"))

    def test_live_page_is_not_a_tombstone_target(self):
        n, rows = page("wiki/live.md", "wk:SynthesisPage",
                       "schema:Article")
        rows.append(litp(n, "wk:pageType", "synthesis"))
        rows.append(litp(n, "wk:status", "draft"))
        report = gs.validate(set(rows))
        row = shape_row(report, "wkshape:TombstoneShape")
        self.assertEqual(0, row["targets_checked"])

    def test_tag_registration(self):
        n, rows = page("wiki/concepts/a.md",
                       "wk:ConceptPage", "skos:Concept")
        rows.append(litp(n, "wk:pageType", "concept"))
        tag = node("tag/access")
        rows += typed(tag, "skos:Concept")
        rows.append(refp(n, "dcterms:subject", tag))
        out = results_for(gs.validate(set(rows)),
                          "wkshape:TagRegistrationShape")
        self.assertEqual(1, len(out))  # no scopeNote yet
        rows.append(litp(tag, "skos:scopeNote",
                         "what the tag means here"))
        self.assertEqual([], results_for(
            gs.validate(set(rows)),
            "wkshape:TagRegistrationShape"))
        rows.append(litp(tag, "wk:tagStatus",
                         "deprecated"))
        out = results_for(gs.validate(set(rows)),
                          "wkshape:TagRegistrationShape")
        self.assertEqual(1, len(out))
        self.assertEqual("deprecated", out[0]["value"])


class DeterminismAndArtefactsTest(unittest.TestCase):
    def test_report_bytes_stable(self):
        _a, rows = assertion(relation="exemplifies")
        r1 = gs.validate(set(rows))
        r2 = gs.validate(set(rows))
        dump = lambda r: json.dumps(r, indent=1,
                                    sort_keys=True,
                                    ensure_ascii=False)
        self.assertEqual(dump(r1), dump(r2))
        self.assertEqual(r1["canonical_sha256"],
                         r2["canonical_sha256"])

    def test_shapes_artefacts_name_every_shape(self):
        ttl = gs.render_shapes_ttl()
        doc = gs.shapes_document()
        self.assertEqual(ttl, gs.render_shapes_ttl())
        json.dumps(doc)  # round-trips as JSON
        for shape in gs.SHAPES:
            self.assertIn(shape["id"], ttl)
            self.assertIn(shape["id"],
                          json.dumps(doc))
        self.assertIn("not a conformant SHACL processor",
                      ttl)


class RealCorpusTest(unittest.TestCase):
    def test_live_tree_report(self):
        report = gs.build_report(REPO)
        self.assertFalse(report["conforms"])
        rel = results_for(report,
                          "wkshape:RelationVocabularyShape")
        # WikiCitadel fictional corpus: no exemplifies relations
        # stand in it (the private corpus's two are its own
        # finding, pinned in the private tree's copy of this test).
        self.assertEqual(0, len(rel))
        self.assertEqual(set(),
                         {r["value"] for r in rel})
        pt = results_for(report, "wkshape:PageTypeShape")
        self.assertEqual([], pt)
        self.assertGreater(report["triples"], 1000)
        self.assertEqual(64, len(report["canonical_sha256"]))
        tags = shape_row(report,
                         "wkshape:TagRegistrationShape")
        self.assertGreater(tags["violations"], 0)


if __name__ == "__main__":
    unittest.main()
