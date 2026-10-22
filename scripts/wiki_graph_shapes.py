#!/usr/bin/env python3
"""wiki_graph_shapes.py — SHACL-AF pattern graph shape
validation for the wiki graph (build wave 6, item W6).

The build list's item, in its own words: "Borrow the
SHACL-AF custom-target/annotation pattern into our
schema-check tooling (Round 13 filing) so checks can target
page classes by annotation rather than path lists — no RDF
stack adopted." This tool is that borrowing, applied to the
linked-data export (scripts/wiki_linked_data.py): the
wiki's structural invariants — the ones the schema already
states in prose — are expressed as SHACL-style SHAPES whose
targets are node CLASSES and property annotations (never
path lists), and the exported triple set is validated
against them.

WHAT THIS IS AND IS NOT. This is a SHACL-PATTERN
validation: shapes in the W3C SHACL vocabulary's shape,
a validation report in the SHACL validation-report
shape (conforms + per-result focus node / path / value /
message). It is NOT a conformant SHACL processor: no
SHACL engine (pyshacl, rdflib) exists on this machine and
none was installed; the checker is this tree's own stdlib
code over the export's triple set. The shapes are ALSO
emitted in Turtle (shapes.ttl) — core-checkable clauses
as sh:property shapes, relational clauses as
sh:SPARQLConstraint — so a real engine could run them
later; the house checker does not execute the SPARQL and
says so here and in every report.

THE CUSTOM-TARGET POINT (the item's core). A shape's
target is a class (wk:SynthesisPage…), a property
annotation (objects of dcterms:subject), or a property
VALUE (pages whose wk:status is "tombstoned") — SHACL /
SHACL-AF target forms. The corpus's two structural pages
(wiki/index.md, wiki/log.md — the schema's own text
recognises them as frontmatter-less) fall outside the
compiled-page target class BY CLASS, not by a name list:
they are typed only wk:Page, carry no wk:pageType, and
the compiled-page shapes never see them.

GROUNDING. Every shape mechanises a rule the schema or
the record actually states; the shape table (SHAPES)
names its prose source, and the report dumps the table.
Invariants with no stated rule are NOT shapes — two are
named as proposals in the build note instead. Known
limits of mechanising over the EXPORT (stated in every
report's gap list): the tombstone reason/date fields are
not in the export's mapping table, so the tombstone
shape checks the replacement half of the rule only; and
the declared-inverse shape validates the exported
graph's internal consistency (the exporter emits declared
pairs together) — declaration-level pair agreement on the
pages themselves is the wiki validator / lint's ground.

DETERMINISM. Same triple set -> identical report bytes:
results stable-sorted, JSON key-sorted, no timestamps.
The report header carries the validated triple set's
canonical SHA-256 (the export's own canonize step) and
the corpus commit as DATA.

Read-only over the corpus: the tool writes only into its
--out directory. Exit: 0 ok, 1 check failed, 2 usage.
Stdlib only, no network.

Licence route: clean re-implementation of the SHACL
pattern from the public standards — W3C SHACL
(Recommendation, 20 July 2017) and SHACL Advanced
Features (W3C Working Group Note) — credited here; no
code or text copied from any implementation.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ld = _load("wiki_linked_data_for_shapes",
           ROOT / "scripts" / "wiki_linked_data.py")

E = ld.expand
Q = ld.qname
RDF_TYPE = ld.RDF_TYPE
XSD_DECIMAL = ld.XSD + "decimal"

SHAPES_VERSION = "1.0.0"
BASE = ld.BASE

# ---------------------------------------------------------------------------
# Vocabularies the shapes close over — each restated from
# its prose source (named per shape in SHAPES below).
# ---------------------------------------------------------------------------

PAGE_TYPES = ["source", "entity", "concept", "synthesis",
              "query"]
PRIMARY_CLASS = {"source": "wk:SourcePage",
                 "entity": "wk:EntityPage",
                 "concept": "wk:ConceptPage",
                 "synthesis": "wk:SynthesisPage",
                 "query": "wk:QueryPage"}
TYPED_PAGE_CLASSES = [E(c) for c in PRIMARY_CLASS.values()]
ALL_PAGE_CLASSES = TYPED_PAGE_CLASSES + [E("wk:Page")]

# wiki/rules/relation-vocabulary.md: the ten adopted terms
# + the grounds/is-grounded-by local extension (amendment
# 2026-10-20) + mentions, the untyped default the page
# itself names as always available.
CLOSED_RELATIONS = ["cites", "contradicts", "corrects",
                    "derives-from", "extends", "grounds",
                    "is-cited-by", "is-corrected-by",
                    "is-grounded-by", "is-superseded-by",
                    "mentions", "replaces-part-of",
                    "supersedes"]

PROVENANCE_LABELS = ["EXTRACTED", "INFERRED", "AMBIGUOUS"]
POLARITIES = ["positive", "negative"]

# Relation predicates whose vocabulary entry declares an
# inverse (relation-vocabulary.md's table): predicate ->
# the inverse predicate the pair must agree over.
INVERSE_PAIRS = [("dcterms:replaces", "dcterms:isReplacedBy"),
                 ("wk:corrects", "wk:isCorrectedBy"),
                 ("wk:grounds", "wk:isGroundedBy"),
                 ("wk:contradicts", "wk:contradicts"),
                 ("cito:cites", "cito:isCitedBy")]

# ---------------------------------------------------------------------------
# The shape table. Each shape: id, name, the target in
# words (class / property / value target — never a path
# list), the prose rule it mechanises (rule_source), and
# its clause descriptors. The table is dumped verbatim
# into shapes.json and the report, so a reader can tell
# exactly which prose rule became which check.
# ---------------------------------------------------------------------------

SHAPES = [
    {"id": "wkshape:PageTypeShape",
     "name": "Compiled page type is declared and agrees "
             "with its class",
     "target": {"kind": "class",
                "classes": ["wk:SourcePage", "wk:EntityPage",
                            "wk:ConceptPage",
                            "wk:SynthesisPage", "wk:QueryPage"],
                "in_words": "every node carrying one of the "
                            "five typed page classes"},
     "rule_source": "AGENTS.md, Page conventions: "
                    "frontmatter `type` is one of (source | "
                    "entity | concept | synthesis | query) "
                    "on every wiki page",
     "clauses": [
         {"kind": "count", "path": "wk:pageType",
          "exactly": 1},
         {"kind": "in", "path": "wk:pageType",
          "values": PAGE_TYPES},
         {"kind": "class-agreement", "path": "wk:pageType",
          "primary_class": PRIMARY_CLASS}]},
    {"id": "wkshape:PageTypeVocabularyShape",
     "name": "A declared page type is in the closed "
             "vocabulary",
     "target": {"kind": "class", "classes": ["wk:Page"],
                "in_words": "every node typed only with the "
                            "generic wk:Page class (pages "
                            "whose type the exporter could "
                            "not map, and the structural "
                            "pages)"},
     "rule_source": "AGENTS.md, Page conventions (the same "
                    "closed type list); a type outside it "
                    "is not a page type here",
     "clauses": [
         {"kind": "in", "path": "wk:pageType",
          "values": PAGE_TYPES,
          "only_when_present": True}]},
    {"id": "wkshape:RelationVocabularyShape",
     "name": "Edge relation is in the closed relation "
             "vocabulary",
     "target": {"kind": "class",
                "classes": ["wk:EdgeAssertion"],
                "in_words": "every edge assertion node"},
     "rule_source": "wiki/rules/relation-vocabulary.md: "
                    "\"Closed. A relation outside this "
                    "list is not declared\" (the ten "
                    "adopted terms + the grounds extension "
                    "of 2026-10-20 + mentions, the untyped "
                    "default)",
     "clauses": [
         {"kind": "count", "path": "wk:relation",
          "exactly": 1},
         {"kind": "in", "path": "wk:relation",
          "values": CLOSED_RELATIONS}]},
    {"id": "wkshape:DeclaredInverseShape",
     "name": "A declared relation between two of our "
             "pages carries its declared inverse",
     "target": {"kind": "triples",
                "in_words": "every direct triple under a "
                            "predicate whose vocabulary "
                            "entry declares an inverse, "
                            "where BOTH endpoints are "
                            "page nodes (\"when both pages "
                            "are ours\")"},
     "rule_source": "wiki/rules/relation-vocabulary.md, "
                    "Rules of use: \"When both pages are "
                    "ours, the inverse is written on the "
                    "target too, and the pair must agree\"",
     "clauses": [
         {"kind": "inverse-pair",
          "pairs": [[a, b] for a, b in INVERSE_PAIRS]}]},
    {"id": "wkshape:EdgeProvenanceShape",
     "name": "Every edge carries its provenance label, "
             "confidence and polarity",
     "target": {"kind": "class",
                "classes": ["wk:EdgeAssertion"],
                "in_words": "every edge assertion node"},
     "rule_source": "The W1.8 edge-label model "
                    "(tools/lens/lenslib.py edge-label "
                    "section; scripts/wiki_edge_labels.py "
                    "check: every door edge carries a "
                    "label from the closed set with a "
                    "confidence in [0, 1])",
     "clauses": [
         {"kind": "count", "path": "wk:provenanceLabel",
          "exactly": 1},
         {"kind": "in", "path": "wk:provenanceLabel",
          "values": PROVENANCE_LABELS},
         {"kind": "count", "path": "wk:edgeConfidence",
          "exactly": 1},
         {"kind": "decimal-range", "path": "wk:edgeConfidence",
          "min": 0.0, "max": 1.0},
         {"kind": "count", "path": "wk:polarity",
          "exactly": 1},
         {"kind": "in", "path": "wk:polarity",
          "values": POLARITIES}]},
    {"id": "wkshape:ClaimShape",
     "name": "A claim is stated, dated, on a real page, "
             "and its page rests on a source",
     "target": {"kind": "class", "classes": ["wk:Claim"],
                "in_words": "every claim node"},
     "rule_source": "AGENTS.md, Outcome-verified claims: "
                    "a claim page opts in with frontmatter "
                    "`claim:` (one falsifiable sentence) + "
                    "`as_of:`; Page conventions: `sources` "
                    "is a required frontmatter element — "
                    "the claim's evidence is its page's "
                    "sources, carried in the graph as the "
                    "page's outgoing cito:cites",
     "clauses": [
         {"kind": "count", "path": "wk:claimText",
          "min": 1},
         {"kind": "count", "path": "wk:statedOn",
          "exactly": 1},
         {"kind": "target-class", "path": "wk:statedOn",
          "classes": ["wk:Page-classes"]},
         {"kind": "count", "path": "wk:asOf", "min": 1},
         {"kind": "joined-count", "path": "wk:statedOn",
          "then": "cito:cites", "min": 1}]},
    {"id": "wkshape:CitationShape",
     "name": "A citation is locked, anchored, and its "
             "target resolves",
     "target": {"kind": "class", "classes": ["wk:Citation"],
                "in_words": "every citation node (the "
                            "citation lockfile's entries)"},
     "rule_source": "AGENTS.md, Page conventions "
                    "(claim-level citations): \"The path "
                    "is repo-relative and must resolve\"; "
                    "the citation lockfile (evaluation/"
                    "citation-lockfile.json) is the "
                    "machinery that proves a cited source "
                    "has not changed — its entries carry "
                    "the content hash and the quote "
                    "selector",
     "clauses": [
         {"kind": "count", "path": "wk:onPage",
          "exactly": 1},
         {"kind": "target-class", "path": "wk:onPage",
          "classes": ["wk:Page-classes"]},
         {"kind": "count", "path": "wk:citesSource",
          "exactly": 1},
         {"kind": "target-typed", "path": "wk:citesSource"},
         {"kind": "count", "path": "wk:contentHash",
          "min": 1},
         {"kind": "count", "path": "wk:hasSelector",
          "min": 1},
         {"kind": "target-class", "path": "wk:hasSelector",
          "classes": ["oa:TextQuoteSelector"]},
         {"kind": "resolves-on-disk",
          "path": "wk:citesSource"}]},
    {"id": "wkshape:TombstoneShape",
     "name": "A tombstone declares its replacement",
     "target": {"kind": "value",
                "path": "wk:status", "value": "tombstoned",
                "in_words": "every page whose wk:status is "
                            "\"tombstoned\" (a value target — "
                            "the SHACL-AF custom-target "
                            "form)"},
     "rule_source": "wiki/rules/relation-vocabulary.md, "
                    "Tombstones + AGENTS.md, Tombstones: a "
                    "tombstone carries `replaced_by` when "
                    "there is a replacement and declares "
                    "the is-superseded-by relation. HALF "
                    "MECHANISED: the export's mapping "
                    "carries wk:status but not the "
                    "tombstone reason/date fields, so this "
                    "shape checks the replacement half "
                    "only (see the report's gap list)",
     "clauses": [
         {"kind": "inverse-exists",
          "predicate": "dcterms:replaces",
          "in_words": "some page node stands in "
                      "dcterms:replaces to the tombstone "
                      "(the graph form of its declared "
                      "is-superseded-by)"}]},
    {"id": "wkshape:TagRegistrationShape",
     "name": "A tag in use is registered",
     "target": {"kind": "objects-of",
                "path": "dcterms:subject",
                "in_words": "every node that is the object "
                            "of a dcterms:subject triple "
                            "(tags actually used on pages)"},
     "rule_source": "AGENTS.md, Tag registry: (1) \"A tag "
                    "is registered at first use\"; (2) \"A "
                    "concept's scopeNote says what the tag "
                    "means here\" — the export joins a used "
                    "tag to its registry row and emits "
                    "skos:scopeNote exactly when the join "
                    "succeeds, so a used tag with no "
                    "scopeNote is an unregistered tag in "
                    "use; (3) deprecation supersedes — a "
                    "deprecated tag still in use is named",
     "clauses": [
         {"kind": "count", "path": "skos:scopeNote",
          "min": 1},
         {"kind": "not-value", "path": "wk:tagStatus",
          "value": "deprecated"}]},
]

GAPS = [
    "Tombstone reason/date: AGENTS.md's tombstone rule "
    "also requires `tombstoned: <date>` and "
    "`tombstone_reason: <why>`; neither field is in the "
    "linked-data export's mapping table, so no triple "
    "carries them and that half of the rule cannot be "
    "checked over this export. (No page in the corpus is "
    "tombstoned today, so the gap is latent, not live.)",
    "Declared-inverse agreement is checked over the "
    "exported graph's direct triples; the exporter emits "
    "a declared pair together, so this shape guards the "
    "export's internal consistency and any future "
    "pipeline change — whether the two PAGES' frontmatter "
    "declarations agree is the wiki validator / lint's "
    "ground, not this report's.",
    "Citation resolution is checked against the corpus "
    "on disk at validation time (the resolve rule is "
    "about files); a validation run without a corpus "
    "root skips that clause and says so in its notes.",
]

PATTERN_STATEMENT = (
    "SHACL-pattern validation (W3C SHACL / SHACL-AF "
    "pattern, house re-implementation): shapes target "
    "node classes and property annotations, never path "
    "lists. This report is NOT the output of a conformant "
    "SHACL processor; shapes.ttl beside it carries the "
    "same shapes for a real engine.")


# ---------------------------------------------------------------------------
# Indexing one triple set
# ---------------------------------------------------------------------------

class Graph:
    def __init__(self, T):
        self.T = T
        self.by_s = {}
        self.types = {}
        for (s, p, o) in T:
            self.by_s.setdefault(s, {}).setdefault(
                p, []).append(o)
            if p == RDF_TYPE and o[0] == "iri":
                self.types.setdefault(s, set()).add(o[1])

    def values(self, s, pred):
        return self.by_s.get(s, {}).get(E(pred), [])

    def lits(self, s, pred):
        return [o[1] for o in self.values(s, pred)
                if o[0] == "lit"]

    def iris(self, s, pred):
        return [o[1] for o in self.values(s, pred)
                if o[0] == "iri"]

    def is_page(self, node):
        return bool(self.types.get(node, set())
                    & set(ALL_PAGE_CLASSES))

    def subjects_with(self, pred, obj):
        return sorted(s for (s, p, o) in self.T
                      if p == E(pred) and o == obj)


def _result(shape_id, focus, path, value, message):
    return {"focusNode": Q(focus) if focus else None,
            "message": message,
            "resultPath": Q(E(path)) if path else None,
            "severity": "Violation",
            "sourceShape": shape_id,
            "value": value}


def _lit_str(obj):
    return obj[1]


# ---------------------------------------------------------------------------
# Shape checkers — one function per shape; each returns
# (targets_checked, [results]).
# ---------------------------------------------------------------------------

def check_page_type(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if cls & set(TYPED_PAGE_CLASSES))
    for node in targets:
        vals = g.lits(node, "wk:pageType")
        if len(vals) != 1:
            out.append(_result(
                sid, node, "wk:pageType",
                f"{len(vals)} values",
                "compiled page must carry exactly one "
                "wk:pageType; carries "
                f"{len(vals)}"))
            continue
        v = vals[0]
        if v not in PAGE_TYPES:
            out.append(_result(
                sid, node, "wk:pageType", v,
                f"page type {v!r} is outside the closed "
                "vocabulary (source | entity | concept | "
                "synthesis | query)"))
            continue
        if E(PRIMARY_CLASS[v]) not in g.types.get(node,
                                                  set()):
            out.append(_result(
                sid, node, "rdf:type", v,
                f"page declares type {v!r} but is not "
                f"typed {PRIMARY_CLASS[v]} in the graph"))
    return len(targets), out


def check_page_type_vocabulary(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if cls == {E("wk:Page")})
    for node in targets:
        for v in g.lits(node, "wk:pageType"):
            if v not in PAGE_TYPES:
                out.append(_result(
                    sid, node, "wk:pageType", v,
                    f"declared page type {v!r} is outside "
                    "the closed vocabulary (source | "
                    "entity | concept | synthesis | "
                    "query); the exporter could only type "
                    "the page as generic wk:Page"))
    return len(targets), out


def check_relation_vocabulary(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if E("wk:EdgeAssertion") in cls)
    for node in targets:
        vals = g.lits(node, "wk:relation")
        if len(vals) != 1:
            out.append(_result(
                sid, node, "wk:relation",
                f"{len(vals)} values",
                "edge assertion must carry exactly one "
                f"wk:relation; carries {len(vals)}"))
            continue
        if vals[0] not in CLOSED_RELATIONS:
            out.append(_result(
                sid, node, "wk:relation", vals[0],
                f"relation {vals[0]!r} is outside the "
                "closed relation vocabulary "
                "(relation-vocabulary.md: \"A relation "
                "outside this list is not declared\")"))
    return len(targets), out


def check_declared_inverse(g, shape):
    sid = shape["id"]
    out = []
    checked = 0
    def sort_key(t):
        s, p, o = t
        return (s, p, o[0], o[1],
                o[2] if len(o) > 2 and o[2] else "")
    for fwd, inv in INVERSE_PAIRS:
        fp, ip = E(fwd), E(inv)
        for (s, p, o) in sorted(g.T, key=sort_key):
            if p != fp or o[0] != "iri":
                continue
            if not (g.is_page(s) and g.is_page(o[1])):
                continue
            checked += 1
            if (o[1], ip, ("iri", s)) not in g.T:
                out.append(_result(
                    sid, s, fwd, Q(o[1]),
                    f"declared relation {Q(fp)} to "
                    f"{Q(o[1])} has no declared inverse "
                    f"{Q(ip)} on the target page; the "
                    "vocabulary requires the pair to "
                    "agree when both pages are ours"))
    return checked, out


def check_edge_provenance(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if E("wk:EdgeAssertion") in cls)
    for node in targets:
        labs = g.lits(node, "wk:provenanceLabel")
        if len(labs) != 1:
            out.append(_result(
                sid, node, "wk:provenanceLabel",
                f"{len(labs)} values",
                "edge assertion must carry exactly one "
                "provenance label; carries "
                f"{len(labs)}"))
        elif labs[0] not in PROVENANCE_LABELS:
            out.append(_result(
                sid, node, "wk:provenanceLabel", labs[0],
                f"provenance label {labs[0]!r} is outside "
                "the closed set (EXTRACTED | INFERRED | "
                "AMBIGUOUS)"))
        confs = g.values(node, "wk:edgeConfidence")
        if len(confs) != 1:
            out.append(_result(
                sid, node, "wk:edgeConfidence",
                f"{len(confs)} values",
                "edge assertion must carry exactly one "
                f"confidence; carries {len(confs)}"))
        else:
            o = confs[0]
            if o[0] != "lit" or o[2] != XSD_DECIMAL:
                out.append(_result(
                    sid, node, "wk:edgeConfidence",
                    _lit_str(o) if o[0] == "lit" else Q(o[1]),
                    "edge confidence is not an xsd:decimal "
                    "literal"))
            else:
                try:
                    v = float(o[1])
                except ValueError:
                    v = None
                if v is None or not (0.0 <= v <= 1.0):
                    out.append(_result(
                        sid, node, "wk:edgeConfidence",
                        o[1],
                        f"edge confidence {o[1]!r} is "
                        "outside [0, 1]"))
        pols = g.lits(node, "wk:polarity")
        if len(pols) != 1:
            out.append(_result(
                sid, node, "wk:polarity",
                f"{len(pols)} values",
                "edge assertion must carry exactly one "
                f"polarity; carries {len(pols)}"))
        elif pols[0] not in POLARITIES:
            out.append(_result(
                sid, node, "wk:polarity", pols[0],
                f"polarity {pols[0]!r} is outside the "
                "closed set (positive | negative)"))
    return len(targets), out


def check_claim(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if E("wk:Claim") in cls)
    for node in targets:
        if len(g.lits(node, "wk:claimText")) < 1:
            out.append(_result(
                sid, node, "wk:claimText", None,
                "claim carries no claim text (the one "
                "falsifiable sentence the claim: field "
                "states)"))
        if len(g.lits(node, "wk:asOf")) < 1:
            out.append(_result(
                sid, node, "wk:asOf", None,
                "claim carries no as_of (the claim "
                "opt-in requires claim: + as_of:)"))
        on = g.iris(node, "wk:statedOn")
        if len(on) != 1:
            out.append(_result(
                sid, node, "wk:statedOn",
                f"{len(on)} values",
                "claim must be stated on exactly one "
                f"page; carries {len(on)}"))
            continue
        page = on[0]
        if not g.is_page(page):
            out.append(_result(
                sid, node, "wk:statedOn", Q(page),
                "claim's statedOn target is not a page "
                "node in the graph"))
            continue
        if not g.iris(page, "cito:cites"):
            out.append(_result(
                sid, node, "cito:cites", Q(page),
                "the claim's page rests on no source in "
                "the graph (no outgoing cito:cites — "
                "its `sources:` evidence is absent)"))
    return len(targets), out


def check_citation(g, shape, root):
    sid = shape["id"]
    out = []
    targets = sorted(s for s, cls in g.types.items()
                     if E("wk:Citation") in cls)
    for node in targets:
        on = g.iris(node, "wk:onPage")
        if len(on) != 1:
            out.append(_result(
                sid, node, "wk:onPage",
                f"{len(on)} values",
                "citation must sit on exactly one page; "
                f"carries {len(on)}"))
        elif not g.is_page(on[0]):
            out.append(_result(
                sid, node, "wk:onPage", Q(on[0]),
                "citation's page is not a page node in "
                "the graph"))
        srcs = g.iris(node, "wk:citesSource")
        if len(srcs) != 1:
            out.append(_result(
                sid, node, "wk:citesSource",
                f"{len(srcs)} values",
                "citation must cite exactly one source; "
                f"carries {len(srcs)}"))
            srcs = []
        for t in srcs:
            if not g.types.get(t):
                out.append(_result(
                    sid, node, "wk:citesSource", Q(t),
                    "citation target is not a typed node "
                    "in the graph"))
            if root is not None and t.startswith(BASE):
                rel = unquote(t[len(BASE):])
                if not (Path(root) / rel).is_file():
                    out.append(_result(
                        sid, node, "wk:citesSource", rel,
                        "citation target does not resolve "
                        f"on disk: {rel} (the citation "
                        "path must resolve)"))
        if len(g.lits(node, "wk:contentHash")) < 1:
            out.append(_result(
                sid, node, "wk:contentHash", None,
                "citation carries no lockfile content "
                "hash — the lock that proves the cited "
                "source has not changed"))
        sels = g.iris(node, "wk:hasSelector")
        if len(sels) < 1:
            out.append(_result(
                sid, node, "wk:hasSelector", None,
                "citation carries no quote selector"))
        for sn in sels:
            if E("oa:TextQuoteSelector") not in \
                    g.types.get(sn, set()):
                out.append(_result(
                    sid, node, "wk:hasSelector", Q(sn),
                    "citation selector is not an "
                    "oa:TextQuoteSelector"))
    return len(targets), out


def check_tombstone(g, shape):
    sid = shape["id"]
    out = []
    targets = g.subjects_with("wk:status",
                              ("lit", "tombstoned", None))
    pred = E("dcterms:replaces")
    replaced = {o[1] for (s, p, o) in g.T
                if p == pred and o[0] == "iri"}
    for node in targets:
        if node not in replaced:
            out.append(_result(
                sid, node, "dcterms:isReplacedBy", None,
                "tombstoned page declares no replacement "
                "in the graph (no page stands in "
                "dcterms:replaces to it — the graph form "
                "of its is-superseded-by declaration)"))
    return len(targets), out


def check_tag_registration(g, shape):
    sid = shape["id"]
    out = []
    targets = sorted({o[1] for (s, p, o) in g.T
                      if p == E("dcterms:subject")
                      and o[0] == "iri"})
    for node in targets:
        if len(g.lits(node, "skos:scopeNote")) < 1:
            out.append(_result(
                sid, node, "skos:scopeNote", None,
                "tag in use carries no skos:scopeNote — "
                "the export found no registry row to "
                "join it to (unregistered tag in use, "
                "or a registry row without a scopeNote)"))
        for st in g.lits(node, "wk:tagStatus"):
            if st == "deprecated":
                out.append(_result(
                    sid, node, "wk:tagStatus", st,
                    "deprecated tag still in use "
                    "(deprecation supersedes; pages keep "
                    "the old tag until migrated — this "
                    "is that naming)"))
    return len(targets), out


CHECKERS = {
    "wkshape:PageTypeShape": check_page_type,
    "wkshape:PageTypeVocabularyShape":
        check_page_type_vocabulary,
    "wkshape:RelationVocabularyShape":
        check_relation_vocabulary,
    "wkshape:DeclaredInverseShape": check_declared_inverse,
    "wkshape:EdgeProvenanceShape": check_edge_provenance,
    "wkshape:ClaimShape": check_claim,
    "wkshape:TombstoneShape": check_tombstone,
    "wkshape:TagRegistrationShape": check_tag_registration,
}


def validate(T, root=None):
    """(report, results) over one triple set. Pure except
    the citation resolution clause, which reads the
    corpus under `root` when given."""
    g = Graph(T)
    results = []
    shape_rows = []
    for shape in SHAPES:
        sid = shape["id"]
        if sid == "wkshape:CitationShape":
            checked, out = check_citation(g, shape, root)
        else:
            checked, out = CHECKERS[sid](g, shape)
        results.extend(out)
        shape_rows.append({
            "id": sid, "name": shape["name"],
            "rule_source": shape["rule_source"],
            "target": shape["target"],
            "targets_checked": checked,
            "violations": len(out)})
    results.sort(key=lambda r: (r["sourceShape"],
                                r["focusNode"] or "",
                                r["resultPath"] or "",
                                r["value"] or "",
                                r["message"]))
    canonical = hashlib.sha256(
        ld.render_ntriples(T).encode("utf-8")).hexdigest()
    notes = []
    if root is None:
        notes.append(
            "citation resolution clause not run: no "
            "corpus root was given, so citation targets "
            "were checked against the graph only")
    report = {
        "canonical_sha256": canonical,
        "conforms": not results,
        "gaps": GAPS,
        "kind": "shacl-pattern-validation-report",
        "notes": notes,
        "pattern": PATTERN_STATEMENT,
        "results": results,
        "shapes": shape_rows,
        "shapes_version": SHAPES_VERSION,
        "tool": "scripts/wiki_graph_shapes.py",
        "triples": len(T),
        "violations": len(results),
    }
    return report


# ---------------------------------------------------------------------------
# Shapes artefacts: shapes.json (the table, verbatim) and
# shapes.ttl (the same shapes in SHACL vocabulary —
# property shapes where SHACL Core expresses the clause,
# sh:SPARQLConstraint where the clause is relational).
# ---------------------------------------------------------------------------

def shapes_document():
    return {"kind": "shacl-pattern-shapes",
            "pattern": PATTERN_STATEMENT,
            "shapes": SHAPES,
            "version": SHAPES_VERSION}


_TTL_HEAD = """# shapes.ttl — the wiki graph shapes in SHACL vocabulary.
#
# Generated by scripts/wiki_graph_shapes.py from its
# shape table (shapes.json carries the same table
# verbatim, with the prose rule each shape mechanises).
# Core-checkable clauses are sh:property shapes;
# relational clauses are sh:SPARQLConstraint so a real
# SHACL engine could run them later. The house checker
# does NOT execute this file or the SPARQL.
# It is a SHACL-pattern validation, not a conformant SHACL processor.
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix wk: <https://wikicitadel.example.org/vocab#> .
@prefix wkshape: <https://wikicitadel.example.org/shapes#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix cito: <http://purl.org/spar/cito/> .
@prefix oa: <http://www.w3.org/ns/oa#> .
@prefix schema: <https://schema.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

"""

_TTL_BODIES = {
    "wkshape:PageTypeShape": """wkshape:PageTypeShape a sh:NodeShape ;
  sh:targetClass wk:SourcePage, wk:EntityPage,
    wk:ConceptPage, wk:SynthesisPage, wk:QueryPage ;
  sh:property [ sh:path wk:pageType ; sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:in ( "source" "entity" "concept" "synthesis"
      "query" ) ] .
# The class<->value agreement clause is relational
# (the node's class must be the primary class of its
# declared type) and is checked by the house checker.
""",
    "wkshape:PageTypeVocabularyShape": """wkshape:PageTypeVocabularyShape a sh:NodeShape ;
  sh:targetClass wk:Page ;
  sh:property [ sh:path wk:pageType ;
    sh:in ( "source" "entity" "concept" "synthesis"
      "query" ) ] .
""",
    "wkshape:RelationVocabularyShape": """wkshape:RelationVocabularyShape a sh:NodeShape ;
  sh:targetClass wk:EdgeAssertion ;
  sh:property [ sh:path wk:relation ; sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:in ( "cites" "contradicts" "corrects"
      "derives-from" "extends" "grounds" "is-cited-by"
      "is-corrected-by" "is-grounded-by"
      "is-superseded-by" "mentions" "replaces-part-of"
      "supersedes" ) ] .
""",
    "wkshape:DeclaredInverseShape": """wkshape:DeclaredInverseShape a sh:NodeShape ;
  sh:targetSubjectsOf dcterms:replaces, wk:corrects,
    wk:grounds, wk:contradicts, cito:cites ;
  sh:sparql [
    sh:message "declared relation has no declared inverse on the target page" ;
    sh:select \"\"\"
      SELECT $this ?value WHERE {
        $this ?pred ?value .
        FILTER (?pred IN (dcterms:replaces, wk:corrects,
          wk:grounds, wk:contradicts, cito:cites))
        # inverse predicate per the vocabulary table;
        # both endpoints must be wiki pages
        FILTER NOT EXISTS { ?value ?inv $this }
      } \"\"\" ] .
""",
    "wkshape:EdgeProvenanceShape": """wkshape:EdgeProvenanceShape a sh:NodeShape ;
  sh:targetClass wk:EdgeAssertion ;
  sh:property [ sh:path wk:provenanceLabel ;
    sh:minCount 1 ; sh:maxCount 1 ;
    sh:in ( "EXTRACTED" "INFERRED" "AMBIGUOUS" ) ] ;
  sh:property [ sh:path wk:edgeConfidence ;
    sh:minCount 1 ; sh:maxCount 1 ;
    sh:datatype xsd:decimal ; sh:minInclusive 0 ;
    sh:maxInclusive 1 ] ;
  sh:property [ sh:path wk:polarity ; sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:in ( "positive" "negative" ) ] .
""",
    "wkshape:ClaimShape": """wkshape:ClaimShape a sh:NodeShape ;
  sh:targetClass wk:Claim ;
  sh:property [ sh:path wk:claimText ; sh:minCount 1 ] ;
  sh:property [ sh:path wk:statedOn ; sh:minCount 1 ;
    sh:maxCount 1 ; sh:class wk:Page ] ;
  sh:property [ sh:path wk:asOf ; sh:minCount 1 ] ;
  sh:sparql [
    sh:message "the claim's page rests on no source" ;
    sh:select \"\"\"
      SELECT $this ?value WHERE {
        $this wk:statedOn ?value .
        FILTER NOT EXISTS { ?value cito:cites ?src }
      } \"\"\" ] .
""",
    "wkshape:CitationShape": """wkshape:CitationShape a sh:NodeShape ;
  sh:targetClass wk:Citation ;
  sh:property [ sh:path wk:onPage ; sh:minCount 1 ;
    sh:maxCount 1 ; sh:class wk:Page ] ;
  sh:property [ sh:path wk:citesSource ; sh:minCount 1 ;
    sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
  sh:property [ sh:path wk:contentHash ;
    sh:minCount 1 ] ;
  sh:property [ sh:path wk:hasSelector ; sh:minCount 1 ;
    sh:class oa:TextQuoteSelector ] .
# The resolution clause (the cited path must resolve
# on disk) is not expressible in SHACL; the house
# checker performs it against the corpus.
""",
    "wkshape:TombstoneShape": """# Value target (the SHACL-AF custom-target form):
# subjects whose wk:status is "tombstoned".
wkshape:TombstoneShape a sh:NodeShape ;
  sh:sparql [
    sh:message "tombstoned page declares no replacement" ;
    sh:select \"\"\"
      SELECT $this WHERE {
        $this wk:status "tombstoned" .
        FILTER NOT EXISTS { ?by dcterms:replaces $this }
      } \"\"\" ] .
""",
    "wkshape:TagRegistrationShape": """wkshape:TagRegistrationShape a sh:NodeShape ;
  sh:targetObjectsOf dcterms:subject ;
  sh:property [ sh:path skos:scopeNote ;
    sh:minCount 1 ] ;
  sh:property [ sh:path wk:tagStatus ;
    sh:not [ sh:hasValue "deprecated" ] ] .
""",
}


def render_shapes_ttl():
    parts = [_TTL_HEAD]
    for shape in SHAPES:
        parts.append(_TTL_BODIES[shape["id"]])
    return "\n".join(parts)


def render_report_md(report, commit):
    lines = [
        "# Graph shape validation — SHACL-pattern report",
        "",
        report["pattern"],
        "",
        f"Corpus commit: {commit or 'unknown'} · "
        f"triples validated: {report['triples']} · "
        "canonical SHA-256: "
        f"`{report['canonical_sha256']}`",
        "",
        f"**Conforms: {report['conforms']}** · "
        f"violations: {report['violations']}",
        "",
        "## Shapes",
        "",
        "| Shape | Targets checked | Violations |",
        "|---|---|---|",
    ]
    for row in report["shapes"]:
        lines.append(f"| {row['id']} | "
                     f"{row['targets_checked']} | "
                     f"{row['violations']} |")
    lines += ["", "## Violations", ""]
    if not report["results"]:
        lines.append("None.")
    for r in report["results"]:
        value = f" = {r['value']}" if r["value"] else ""
        lines.append(f"- **{r['sourceShape']}** · "
                     f"{r['focusNode']} · "
                     f"{r['resultPath'] or '—'}{value} — "
                     f"{r['message']}")
    lines += ["", "## Gaps — what this report cannot "
              "check", ""]
    for gap in report["gaps"]:
        lines.append(f"- {gap}")
    for note in report["notes"]:
        lines.append(f"- Note: {note}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False,
                      sort_keys=True) + "\n"


def _summary(report):
    lines = [f"conforms: {report['conforms']}  "
             f"violations: {report['violations']}  "
             f"triples: {report['triples']}"]
    for row in report["shapes"]:
        lines.append(f"  {row['id']}: "
                     f"{row['targets_checked']} checked, "
                     f"{row['violations']} violations")
    return "\n".join(lines)


def build_report(root):
    T, _counts, _loss, extras = ld.build_triples(root)
    report = validate(T, root=root)
    report["corpus_commit"] = extras.get("commit")
    report["corpus_dirty"] = extras.get("dirty")
    on_disk = Path(root) / "exports" / "linked-data" \
        / "linked-data-report.json"
    if on_disk.is_file():
        try:
            prev = json.loads(
                on_disk.read_text(encoding="utf-8"))
            report["on_disk_export_canonical_sha256"] = \
                prev.get("canonical_sha256")
        except (OSError, ValueError):
            pass
    return report


def cmd_build(args):
    root = Path(args.root)
    out = Path(args.out) if args.out else \
        root / "exports" / "shacl"
    report = build_report(root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shapes.json").write_text(
        _dump(shapes_document()), encoding="utf-8")
    (out / "shapes.ttl").write_text(
        render_shapes_ttl(), encoding="utf-8")
    (out / "validation-report.json").write_text(
        _dump(report), encoding="utf-8")
    (out / "validation-report.md").write_text(
        render_report_md(report, report.get(
            "corpus_commit")), encoding="utf-8")
    print(f"artefacts in {out}")
    print(_summary(report))
    return 0


def cmd_check(args):
    root = Path(args.root)
    out = Path(args.out) if args.out else \
        root / "exports" / "shacl"
    report = build_report(root)
    print(_summary(report))
    failed = not report["conforms"]
    disk_shapes = out / "shapes.json"
    if disk_shapes.is_file():
        if disk_shapes.read_text(encoding="utf-8") != \
                _dump(shapes_document()):
            print("DRIFT: shapes.json on disk differs "
                  "from the shape table")
            failed = True
        disk_ttl = out / "shapes.ttl"
        if disk_ttl.is_file() and \
                disk_ttl.read_text(encoding="utf-8") != \
                render_shapes_ttl():
            print("DRIFT: shapes.ttl on disk differs "
                  "from a fresh render")
            failed = True
        disk_report = out / "validation-report.json"
        if disk_report.is_file():
            try:
                prev = json.loads(disk_report.read_text(
                    encoding="utf-8"))
                if prev.get("canonical_sha256") != \
                        report["canonical_sha256"]:
                    print("STALE: the on-disk report "
                          "validates a different triple "
                          "set (canonical hash differs) "
                          "— re-run build")
                    failed = True
            except ValueError:
                print("DRIFT: on-disk validation report "
                      "does not parse")
                failed = True
    else:
        print("no artefacts on disk yet — run build")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="SHACL-pattern graph shape "
                    "validation for the wiki graph")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None,
                    help="artefact directory (default "
                         "<root>/exports/shacl)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
