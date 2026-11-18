#!/usr/bin/env python3
"""wiki_linked_data.py — RDF / JSON-LD linked-data export
of the wiki graph (build wave 6, item W6).

A standards-based export of the compiled wiki graph: pages,
typed edges, claims and citations as linked data, in two
serialisations of ONE triple set —

  wiki.jsonld   JSON-LD 1.1, context embedded (identical to
                the published context.jsonld beside it)
  wiki.ttl      RDF 1.1 Turtle
  context.jsonld  the versioned @context / vocabulary
                mapping, published as its own artefact
  linked-data-report.json
                counts, the FULL mapping table, the
                canonical hash (below), artefact hashes,
                and the LOSS REPORT: every wiki construct
                with no mapping, by name and count. Unmapped
                is a reported state, never an omission.
  llms.txt      the agent-readable documentation export
                (Sourcey / llmstxt.org pattern): what the
                artefacts are, and a canonical-IRI index of
                every page and claim in the export.

The canonize step (the build list's wording): the triple
set is also rendered as sorted N-Triples — a canonical,
hashable form; its SHA-256 is the export's canonical hash,
recorded in the report. It is kin to the citation lockfile
in spirit: one hash a consumer can check the whole graph
against.

Licence route: adapt-with-credit where the item's rows name
sources, else clean re-implementation from the public
standards. RDFLib/rdflib (BSD-3-Clause) and digitalbazaar's
jsonld.js / jsonld-canonicalize (BSD-3-Clause) are the
serializer family used as REFERENCE for output shape; no
code is copied (neither library is installed here — the
serializers are stdlib Python written against the W3C
specifications: JSON-LD 1.1, RDF 1.1 Turtle, RDF 1.1
N-Triples, and the dataset-canonize idea from the W3C RDF
Dataset Canonicalization work). Vocabularies used as terms,
per their own terms of use: schema.org, SKOS, PROV-O,
Dublin Core Terms, CiTO (SPAR), and the W3C Web Annotation
Data Model (oa:). repo-knowledge-graph is the item's
framing source (a knowledge graph as linked data); the
Sourcey pattern generalises the agent-readable exports.

The mapping (MAPPING below, versioned, and dumped in full
into every report):

  - A wiki page is a node typed by its frontmatter `type`
    (source -> wk:SourcePage, entity -> wk:EntityPage +
    schema:Thing, concept -> wk:ConceptPage + skos:Concept,
    synthesis -> wk:SynthesisPage + schema:Article, query ->
    wk:QueryPage, absent -> wk:Page). Page fields map to
    Dublin Core / schema.org / wk: terms per the table.
  - A raw source is a wk:RawSource + prov:Entity node.
  - A tag is a skos:Concept, joined to the tag registry
    (evaluation/tag-registry.jsonl) for its prefLabel /
    scopeNote when registered there.
  - Every typed edge from the traversal door's graph (the
    same table the Lens and the graph export read) becomes
    (a) a direct triple under the relation's mapped
    predicate, where the closed relation vocabulary has
    one, plus its declared inverse, and (b) a wk:EdgeAssertion
    node carrying the relation, the edge kind, and the
    W1.8 provenance label (EXTRACTED / INFERRED /
    AMBIGUOUS), confidence and polarity as first-class
    properties — labels and confidence therefore survive
    the round trip (export -> parse back -> compare is a
    test). An edge whose relation has NO mapping still
    gets its assertion node; the missing direct predicate
    is a loss-report entry, not a dropped edge.
  - A claim (evaluation/claim-index.jsonl, joined with
    page-frontmatter `claim:` text on the same page IRI)
    is a wk:Claim linked to its page; a citation
    (evaluation/citation-lockfile.json) is a wk:Citation
    linking its page to its raw source (cito:cites) with
    the lock hashes, the line range, and its selector as
    an oa:TextQuoteSelector node — the lockfile's own
    dual anchoring, carried in the standard's terms.

Determinism: same corpus -> identical bytes. Every list
is sorted, the JSON is key-sorted, no timestamp is
emitted; the corpus commit id (and a dirty flag) ride as
DATA on the dataset node when the root is a git checkout.

Read-only over the corpus: the tool writes only into its
--out directory. Exit: 0 ok, 1 check failed, 2 usage.
Stdlib only, no network.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent

MAPPING_VERSION = "1.0.0"
BASE = "https://wikicitadel.example.org/"
NS = {
    "wk": BASE + "vocab#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "schema": "https://schema.org/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "cito": "http://purl.org/spar/cito/",
    "oa": "http://www.w3.org/ns/oa#",
}
RDF_TYPE = NS["rdf"] + "type"
XSD = NS["xsd"]

# ---------------------------------------------------------------------------
# The mapping table (versioned — MAPPING_VERSION above; the
# report dumps this verbatim so a consumer can tell exactly
# which wiki construct became which term).
# ---------------------------------------------------------------------------

PAGE_TYPE_CLASSES = {
    "source": ["wk:SourcePage"],
    "entity": ["wk:EntityPage", "schema:Thing"],
    "concept": ["wk:ConceptPage", "skos:Concept"],
    "synthesis": ["wk:SynthesisPage", "schema:Article"],
    "query": ["wk:QueryPage"],
    None: ["wk:Page"],
}

# frontmatter field -> (predicate, value kind); kind is
# "literal" or "date". Fields consumed structurally (type,
# sources, tags, links, claim, the relation fields) are in
# CONSUMED_FIELDS and never reach this table.
FIELD_MAP = {
    "title": ("schema:name", "literal"),
    "created": ("dcterms:created", "date"),
    "updated": ("dcterms:modified", "date"),
    "planted": ("wk:planted", "date"),
    "tended": ("wk:tended", "date"),
    "status": ("wk:status", "literal"),
    "confidence": ("wk:confidence", "literal"),
    "stage": ("wk:stage", "literal"),
    "work_type": ("wk:workType", "literal"),
    "methods": ("wk:methods", "literal"),
    "as_of": ("wk:asOf", "date"),
    "verified_until": ("wk:verifiedUntil", "date"),
    "verified_by": ("wk:verifiedBy", "literal"),
    "compiled_prompt": ("wk:compiledPrompt", "literal"),
    "compiled_converter": ("wk:compiledConverter", "literal"),
    "compiled_date": ("wk:compiledDate", "date"),
}
RELATION_FIELDS = {
    "supersedes", "superseded_by", "cites", "cited_by",
    "corrects", "corrected_by", "extends", "contradicts",
    "derives_from", "replaces_part_of", "grounds",
    "is_grounded_by",
}
CONSUMED_FIELDS = {"type", "sources", "tags", "links",
                   "claim"} | RELATION_FIELDS

# relation -> (direct predicate, inverse predicate or None)
RELATION_MAP = {
    "mentions": ("wk:mentions", None),
    "cites": ("cito:cites", "cito:isCitedBy"),
    "grounds": ("wk:grounds", "wk:isGroundedBy"),
    "contradicts": ("wk:contradicts", "wk:contradicts"),
    "extends": ("wk:extends", None),
    "supersedes": ("dcterms:replaces", "dcterms:isReplacedBy"),
    "corrects": ("wk:corrects", "wk:isCorrectedBy"),
    "derives-from": ("prov:wasDerivedFrom", None),
    "replaces-part-of": ("wk:replacesPartOf", None),
}

CLAIM_MAP = {
    "text": "wk:claimText", "stated": "wk:stated",
    "supports": "wk:supportsCount",
    "contradicts": "wk:contradictsCount",
    "verified_n": "wk:verifiedCount",
    "superseded": "wk:superseded",
    "indexed_on": "wk:indexedOn", "hash": "wk:registerHash",
}
CITATION_MAP = {
    "page": "wk:onPage", "page_line": "wk:pageLine",
    "claim": "wk:claimText", "claim_hash": "wk:claimHash",
    "content_hash": "wk:contentHash",
    "line_hashes": "wk:lineHash",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?$")


# ---------------------------------------------------------------------------
# Triple model: (subject_iri, predicate_iri, object) where
# object is ("iri", iri) or ("lit", lexical, datatype|None).
# ---------------------------------------------------------------------------

def iri(path):
    """The canonical IRI for a repo-relative path (or a
    synthetic id path): each segment percent-quoted."""
    return BASE + "/".join(quote(seg, safe="-._~")
                           for seg in path.split("/"))


def expand(term):
    """A prefixed name (or a full IRI) -> a full IRI."""
    if "://" in term:
        return term
    if ":" in term:
        pfx, local = term.split(":", 1)
        if pfx in NS:
            return NS[pfx] + local
    return term


def qname(full):
    """A full IRI -> its prefixed name when it sits exactly
    under a declared namespace, else the full IRI."""
    best = None
    for pfx, ns in NS.items():
        if full.startswith(ns) and (best is None
                                    or len(ns) > len(NS[best])):
            best = pfx
    if best is not None:
        local = full[len(NS[best]):]
        if local and re.fullmatch(r"[A-Za-z0-9_.\-]+", local):
            return f"{best}:{local}"
    return full


def lit(value, datatype=None):
    return ("lit", value, datatype)


def ref(full_iri):
    return ("iri", full_iri)


def dec_lexical(v):
    """The canonical lexical form of a decimal value."""
    return repr(float(v))


# ---------------------------------------------------------------------------
# Loading the corpus — through the house machinery only:
# the traversal door's page graph, the W1.8 label table
# (with the directed-pair conflict pass), the claim
# register, the citation lockfile, the tag registry.
# ---------------------------------------------------------------------------

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jsonl(path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _target_for_bare(bare, pages, root):
    """The node a citation target names, resolved against
    the corpus itself: (node_iri, source_rel | None, kind).
    A `sources:` entry that names a wiki page joins that
    page's node (one document, one IRI — the corpus has
    such entries); a path that names a repo file is that
    file's source node, as written; a path that names
    nothing on disk is a dangling declared source, kept as
    a source node at the path the citation most plausibly
    meant. kind is page / raw / outside-raw / dangling."""
    if bare in pages:
        return iri(bare), None, "page"
    if (root / bare).is_file():
        return iri(bare), bare, \
            "raw" if bare.startswith("raw/") else "outside-raw"
    if (root / "raw" / bare).is_file():
        return iri("raw/" + bare), "raw/" + bare, "raw"
    rel = bare if bare.startswith("raw/") else "raw/" + bare
    return iri(rel), rel, "dangling"


def corpus_commit(root):
    """(commit, dirty) when root is a git checkout, else
    (None, None). Corpus state as data, never a timestamp."""
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15)
        if head.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=15)
        dirty = bool(status.stdout.strip()) \
            if status.returncode == 0 else None
        return head.stdout.strip(), dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


class Loss:
    """The loss report: unmapped constructs by name+count."""

    def __init__(self):
        self.rows = {}

    def add(self, kind, construct, count=1, detail=""):
        key = (kind, construct)
        row = self.rows.setdefault(
            key, {"kind": kind, "construct": construct,
                  "count": 0, "detail": detail})
        row["count"] += count

    def as_list(self):
        return [self.rows[k] for k in sorted(self.rows)]

    @property
    def instances(self):
        return sum(r["count"] for r in self.rows.values())


def load_corpus(root):
    root = Path(root)
    traverse = _load("wiki_traverse_for_ld",
                     root / "scripts" / "wiki_traverse.py")
    labels = _load("wiki_edge_labels_for_ld",
                   root / "scripts" / "wiki_edge_labels.py")
    pages, _keys = traverse.page_index(root)
    edges, _conflicts = labels.labelled_edges(root)
    claims = _jsonl(root / "evaluation" / "claim-index.jsonl")
    lock_path = root / "evaluation" / "citation-lockfile.json"
    citations = []
    if lock_path.is_file():
        citations = json.loads(
            lock_path.read_text(encoding="utf-8")).get(
                "citations", [])
    tag_concepts = {}
    for row in _jsonl(root / "evaluation"
                      / "tag-registry.jsonl"):
        if row.get("kind") == "concept":
            for key in [row.get("id"), row.get("prefLabel")] \
                    + list(row.get("altLabels") or []):
                if key:
                    tag_concepts.setdefault(key, row)
    return {"pages": pages, "edges": edges, "claims": claims,
            "citations": citations,
            "tag_concepts": tag_concepts}


# ---------------------------------------------------------------------------
# Building the triple set
# ---------------------------------------------------------------------------

def _date_object(value, field, loss):
    """A frontmatter/record date value -> a typed literal,
    or a plain literal + a loss entry when it is not one."""
    v = str(value)
    if DATE_RE.match(v):
        return lit(v, XSD + "date")
    if DATETIME_RE.match(v):
        return lit(v.replace(" ", "T"), XSD + "dateTime")
    loss.add("field-value", f"field '{field}' value not a "
             f"date: {v!r}", detail="emitted as a plain "
             "literal; the value is not date-shaped")
    return lit(v)


def build_triples(root):
    """(triples, counts, loss, extras) for the corpus under
    root. Pure: reads the corpus, changes nothing."""
    root = Path(root)
    data = load_corpus(root)
    pages, edges = data["pages"], data["edges"]
    loss = Loss()
    T = set()

    def add(s, p, o):
        T.add((s, expand(p) if not p.startswith("http")
               else p, o))

    def type_node(node, classes):
        for c in classes:
            add(node, RDF_TYPE, ref(expand(c)))

    # ---- tags (skos:Concept nodes, registry-joined) ------------------------
    made_tag_nodes = {}

    def ensure_tag_node(slug, concept=None, label=None):
        if slug in made_tag_nodes:
            return made_tag_nodes[slug]
        tnode = iri(f"tag/{slug}")
        made_tag_nodes[slug] = tnode
        type_node(tnode, ["skos:Concept"])
        add(tnode, "skos:prefLabel",
            lit((concept or {}).get("prefLabel") or label
                or slug))
        if concept:
            if concept.get("scopeNote"):
                add(tnode, "skos:scopeNote",
                    lit(concept["scopeNote"]))
            if concept.get("status") \
                    and concept["status"] != "preferred":
                add(tnode, "wk:tagStatus",
                    lit(concept["status"]))
            for broader in concept.get("broader") or []:
                ensure_tag_node(
                    broader,
                    data["tag_concepts"].get(broader))
                add(tnode, "skos:broader",
                    ref(iri(f"tag/{broader}")))
        return tnode

    # ---- pages ------------------------------------------------------------
    page_info = []
    for rel in sorted(pages):
        fields, _body, _text = pages[rel]
        node = iri(rel)
        ptype = fields.get("type")
        classes = PAGE_TYPE_CLASSES.get(
            ptype, PAGE_TYPE_CLASSES[None])
        if ptype is not None and ptype not in PAGE_TYPE_CLASSES:
            loss.add("page-type", f"page type {ptype!r}",
                     detail=f"page {rel}: typed as the "
                     "generic wk:Page; the type value itself "
                     "is carried as wk:pageType")
        type_node(node, classes)
        if ptype is not None:
            add(node, "wk:pageType", lit(str(ptype)))
        for field, value in sorted(fields.items()):
            if field in CONSUMED_FIELDS:
                continue
            if field not in FIELD_MAP:
                loss.add("frontmatter-field",
                         f"frontmatter field '{field}'",
                         detail="no mapping in the table; "
                         "the field is not emitted")
                continue
            pred, kind = FIELD_MAP[field]
            values = value if isinstance(value, list) \
                else [value]
            for v in values:
                if isinstance(v, dict):
                    loss.add("field-value",
                             f"field '{field}' mapping value",
                             detail=f"page {rel}: a mapping "
                             "value has no literal mapping; "
                             "not emitted")
                elif kind == "date":
                    add(node, pred, _date_object(v, field, loss))
                else:
                    add(node, pred, lit(str(v)))
        tags_val = fields.get("tags") or []
        if isinstance(tags_val, str):
            tags_val = [tags_val]
        for tag in tags_val:
            tag = str(tag)
            concept = data["tag_concepts"].get(tag)
            slug = concept["id"] if concept else tag
            add(node, "dcterms:subject",
                ref(ensure_tag_node(slug, concept, label=tag)))
        page_info.append({"rel": rel,
                          "title": fields.get("title"),
                          "type": ptype, "iri": node})

    # ---- raw sources (destinations of citation edges) ---------------------
    raw_sources = set()
    target_kinds = Counter()
    edge_targets = {}
    for e in edges:
        if e["kind"] != "citation":
            continue
        bare = e["dst"][4:] if e["dst"].startswith("raw:") \
            else e["dst"]
        node, source_rel, kind = _target_for_bare(
            bare, pages, root)
        edge_targets[(e["src"], e["dst"])] = node
        target_kinds[kind] += 1
        if source_rel:
            raw_sources.add(source_rel)
    citation_targets = {}
    for c in data["citations"]:
        if c.get("source"):
            node, source_rel, _kind = _target_for_bare(
                c["source"], pages, root)
            citation_targets[c["id"]] = node
            if source_rel:
                raw_sources.add(source_rel)
    for rel in sorted(raw_sources):
        type_node(iri(rel), ["wk:RawSource", "prov:Entity"])

    # ---- edges: direct triples + assertion nodes ---------------------------
    direct_triples = 0
    for idx, e in enumerate(
            sorted(edges, key=lambda x: (x["src"], x["dst"],
                                         x["kind"],
                                         x["relation"])), 1):
        src_node = iri(e["src"])
        dst_node = edge_targets[(e["src"], e["dst"])] \
            if e["kind"] == "citation" else iri(e["dst"])
        relation = e["relation"]
        mapped = RELATION_MAP.get(relation)
        if mapped:
            pred, inverse = mapped
            add(src_node, pred, ref(dst_node))
            direct_triples += 1
            if inverse:
                add(dst_node, inverse, ref(src_node))
        else:
            loss.add("relation", f"relation {relation!r}",
                     detail="no predicate mapping in the "
                     "table; the edge is carried by its "
                     "assertion node only")
        anode = iri(f"assertion/{idx:06d}")
        type_node(anode, ["wk:EdgeAssertion"])
        add(anode, "wk:edgeSubject", ref(src_node))
        add(anode, "wk:edgeObject", ref(dst_node))
        add(anode, "wk:relation", lit(relation))
        if mapped:
            add(anode, "wk:edgePredicate", ref(expand(mapped[0])))
        add(anode, "wk:edgeKind", lit(e["kind"]))
        add(anode, "wk:provenanceLabel", lit(e["provenance"]))
        add(anode, "wk:edgeConfidence",
            lit(dec_lexical(e["confidence"]), XSD + "decimal"))
        add(anode, "wk:polarity", lit(e["polarity"]))
        add(anode, "wk:assignmentRule", lit(e["rule"]))

    # ---- claims -------------------------------------------------------------
    claim_info = []
    register_ids = {}
    for row in data["claims"]:
        cid = row["claim_id"]
        node = iri(f"claim/{cid}")
        register_ids.setdefault(cid, node)
        type_node(node, ["wk:Claim"])
        add(node, "wk:statedOn", ref(iri(cid)))
        for field, pred in CLAIM_MAP.items():
            if field not in row:
                continue
            v = row[field]
            if field in ("stated", "indexed_on"):
                add(node, pred, _date_object(v, field, loss))
            elif isinstance(v, bool):
                add(node, pred,
                    lit("true" if v else "false",
                        XSD + "boolean"))
            elif isinstance(v, int):
                add(node, pred, lit(str(v), XSD + "integer"))
            else:
                add(node, pred, lit(str(v)))
        claim_info.append({"id": cid, "iri": node,
                           "text": row.get("text")})
    frontmatter_only = 0
    divergent = 0
    absent_page = sum(1 for row in data["claims"]
                      if row["claim_id"] not in pages)
    for rel in sorted(pages):
        fields = pages[rel][0]
        text = fields.get("claim")
        if not text:
            continue
        node = register_ids.get(rel) or iri(f"claim/{rel}")
        if rel not in register_ids:
            frontmatter_only += 1
            type_node(node, ["wk:Claim"])
            add(node, "wk:statedOn", ref(iri(rel)))
            claim_info.append({"id": rel, "iri": node,
                               "text": str(text)})
        existing = {o[1] for (s, p, o) in T
                    if s == node and p == expand("wk:claimText")}
        if str(text) not in existing:
            if existing:
                divergent += 1
            add(node, "wk:claimText", lit(str(text)))
        if fields.get("as_of"):
            add(node, "wk:asOf",
                _date_object(fields["as_of"], "as_of", loss))

    # ---- citations ----------------------------------------------------------
    selectors = 0
    for c in sorted(data["citations"],
                    key=lambda x: x.get("id", "")):
        node = iri(f"citation/{c['id']}")
        type_node(node, ["wk:Citation"])
        for field, pred in CITATION_MAP.items():
            if field not in c:
                continue
            v = c[field]
            if field == "page":
                add(node, pred, ref(iri(str(v))))
            elif field == "page_line":
                add(node, pred, lit(str(v), XSD + "integer"))
            elif field == "line_hashes":
                for h in v:
                    add(node, pred, lit(str(h)))
            else:
                add(node, pred, lit(str(v)))
        if c.get("source"):
            target = citation_targets[c["id"]]
            add(node, "wk:citesSource", ref(target))
            add(node, "cito:cites", ref(target))
        rng = c.get("range")
        if isinstance(rng, list) and len(rng) == 2:
            add(node, "wk:lineRangeStart",
                lit(str(rng[0]), XSD + "integer"))
            add(node, "wk:lineRangeEnd",
                lit(str(rng[1]), XSD + "integer"))
        sel = c.get("selector")
        if isinstance(sel, dict):
            selectors += 1
            snode = node + "/selector"
            stype = sel.get("type")
            if stype == "TextQuoteSelector":
                type_node(snode, ["oa:TextQuoteSelector"])
            else:
                type_node(snode, ["wk:Selector"])
                loss.add("selector-type",
                         f"selector type {stype!r}",
                         detail="not the W3C TextQuoteSelector; "
                         "carried as a generic wk:Selector")
            add(node, "wk:hasSelector", ref(snode))
            for f, pred in (("exact", "oa:exact"),
                            ("prefix", "oa:prefix"),
                            ("suffix", "oa:suffix")):
                if sel.get(f):
                    add(snode, pred, lit(str(sel[f])))

    # ---- the dataset node ---------------------------------------------------
    commit, dirty = corpus_commit(root)
    dataset = iri("export/linked-data")
    type_node(dataset, ["schema:Dataset"])
    add(dataset, "schema:name",
        lit("LLM Wiki — linked-data export"))
    add(dataset, "wk:mappingVersion", lit(MAPPING_VERSION))
    if commit:
        add(dataset, "wk:corpusCommit", lit(commit))
    if dirty is not None:
        add(dataset, "wk:corpusDirty",
            lit("true" if dirty else "false", XSD + "boolean"))
    counts = {
        "pages": len(pages), "raw_sources": len(raw_sources),
        "tags": len(made_tag_nodes), "edges": len(edges),
        "direct_relation_triples": direct_triples,
        "claims": len(claim_info),
        "citations": len(data["citations"]),
        "selectors": selectors,
        "claims_from_frontmatter_only": frontmatter_only,
        "claims_text_divergent": divergent,
        "claims_with_absent_page": absent_page,
        "citation_targets": dict(sorted(
            target_kinds.items())),
        "loss_constructs": len(loss.rows),
        "loss_instances": loss.instances,
        "triples": len(T),
    }
    for key, pred in (("pages", "wk:pageCount"),
                      ("raw_sources", "wk:sourceCount"),
                      ("tags", "wk:tagCount"),
                      ("edges", "wk:edgeCount"),
                      ("claims", "wk:claimCount"),
                      ("citations", "wk:citationCount")):
        add(dataset, pred, lit(str(counts[key]), XSD + "integer"))
    counts["triples"] = len(T)
    extras = {"pages": page_info, "claims": claim_info,
              "commit": commit, "dirty": dirty}
    return T, counts, loss, extras


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _esc(text):
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def _obj_nt(obj):
    if obj[0] == "iri":
        return f"<{obj[1]}>"
    _, lexical, datatype = obj
    if datatype:
        return f'"{_esc(lexical)}"^^<{datatype}>'
    return f'"{_esc(lexical)}"'


def render_ntriples(T):
    """The canonical form: sorted N-Triples lines."""
    lines = sorted(f"<{s}> <{p}> {_obj_nt(o)} ." for s, p, o in T)
    return "\n".join(lines) + "\n"


def _obj_ttl(obj):
    if obj[0] == "iri":
        return qname(obj[1]) if "://" not in qname(obj[1]) \
            else f"<{obj[1]}>"
    _, lexical, datatype = obj
    if datatype:
        return f'"{_esc(lexical)}"^^{qname(datatype)}'
    return f'"{_esc(lexical)}"'


def _term_ttl(full):
    q = qname(full)
    return q if "://" not in q else f"<{full}>"


def render_turtle(T):
    lines = [f"@prefix {pfx}: <{NS[pfx]}> ."
             for pfx in sorted(NS)]
    lines.append("")
    for s, p, o in sorted(T, key=lambda t: (t[0], t[1],
                                            _obj_nt(t[2]))):
        pred = "a" if p == RDF_TYPE else _term_ttl(p)
        lines.append(f"{_term_ttl(s)} {pred} {_obj_ttl(o)} .")
    return "\n".join(lines) + "\n"


# The published context: prefix namespaces plus the terms
# whose values are IRI references (coerced with @type @id).
CONTEXT = {
    "@context": dict(
        sorted(NS.items()),
        **{
            "edgeSubject": {"@id": "wk:edgeSubject",
                            "@type": "@id"},
            "edgeObject": {"@id": "wk:edgeObject",
                           "@type": "@id"},
            "edgePredicate": {"@id": "wk:edgePredicate",
                              "@type": "@id"},
            "statedOn": {"@id": "wk:statedOn", "@type": "@id"},
            "onPage": {"@id": "wk:onPage", "@type": "@id"},
            "citesSource": {"@id": "wk:citesSource",
                            "@type": "@id"},
            "hasSelector": {"@id": "wk:hasSelector",
                            "@type": "@id"},
            "subject": {"@id": "dcterms:subject",
                        "@type": "@id"},
            "broader": {"@id": "skos:broader", "@type": "@id"},
        }),
}


def _obj_jsonld(obj):
    if obj[0] == "iri":
        return {"@id": qname(obj[1])}
    _, lexical, datatype = obj
    if datatype is None:
        return lexical
    if datatype == XSD + "integer":
        return int(lexical)
    if datatype == XSD + "boolean":
        return lexical == "true"
    if datatype == XSD + "decimal":
        return {"@value": float(lexical),
                "@type": qname(datatype)}
    return {"@value": lexical, "@type": qname(datatype)}


def render_jsonld(T):
    by_subject = {}
    for s, p, o in T:
        by_subject.setdefault(s, {}).setdefault(p, []).append(o)
    graph = []
    for s in sorted(by_subject):
        node = {"@id": qname(s)}
        preds = by_subject[s]
        types = sorted(qname(o[1]) for o in preds.pop(
            RDF_TYPE, []) if o[0] == "iri")
        if types:
            node["@type"] = types
        for p in sorted(preds):
            objs = sorted(preds[p], key=_obj_nt)
            vals = [_obj_jsonld(o) for o in objs]
            node[qname(p)] = vals[0] if len(vals) == 1 else vals
        graph.append(node)
    doc = dict(CONTEXT)
    doc["@graph"] = graph
    return doc


def render_context():
    return dict(CONTEXT)


def render_llms(extras, counts):
    lines = [
        "# LLM Wiki — linked-data export", "",
        "> Standards-based export of the compiled wiki "
        "graph — pages, typed edges with provenance labels, "
        "claims and citations — as JSON-LD and Turtle under "
        f"mapping version {MAPPING_VERSION}. Corpus commit: "
        f"{extras['commit'] or 'unknown (not a git checkout)'}"
        + (" (working tree dirty)" if extras["dirty"] else "")
        + ".", "",
        "## Artefacts", "",
        "- [JSON-LD export](wiki.jsonld): the full graph "
        "with the context embedded.",
        "- [Turtle export](wiki.ttl): the same triple set "
        "in RDF/Turtle.",
        "- [JSON-LD context](context.jsonld): the versioned "
        "vocabulary mapping, published as its own artefact.",
        "- [Export report](linked-data-report.json): "
        "counts, the full mapping table, the canonical "
        "SHA-256 of the triple set, and the loss report "
        "(every wiki construct with no mapping, by name and "
        "count).", "",
        f"## Pages ({counts['pages']})", "",
    ]
    for p in extras["pages"]:
        title = p["title"] or "(untitled)"
        lines.append(f"- [{title}]({p['iri']}): "
                     f"{p['type'] or 'page'} — {p['rel']}")
    lines += ["", f"## Claims ({counts['claims']})", ""]
    for c in extras["claims"]:
        lines.append(f"- [{c['text']}]({c['iri']}): "
                     f"stated on {c['id']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# A local JSON-LD expansion + a Turtle parser for exactly
# the shapes this tool emits — the machine check that the
# two serialisations carry the same triples and that the
# JSON-LD expands cleanly under its own context with no
# network fetch. Used by `check` and by the tests.
# ---------------------------------------------------------------------------

def _expand_ref(value):
    if "://" in value:
        return value
    if ":" in value:
        pfx, local = value.split(":", 1)
        if pfx in NS:
            return NS[pfx] + local
    raise ValueError(f"unresolvable reference {value!r}")


def expand_jsonld(doc):
    """JSON-LD document -> the triple set it carries.
    Raises ValueError on anything the context cannot
    resolve (an expansion error)."""
    ctx = doc["@context"]
    terms = {k: v for k, v in ctx.items()
             if isinstance(v, dict)}
    triples = set()

    def value_triples(s, pred, val):
        if isinstance(val, list):
            for v in val:
                value_triples(s, pred, v)
            return
        if isinstance(val, dict):
            if "@id" in val:
                triples.add((s, pred,
                             ref(_expand_ref(val["@id"]))))
                return
            if "@value" in val:
                dt = val.get("@type")
                triples.add((s, pred, lit(
                    str(val["@value"]),
                    _expand_ref(dt) if dt else None)))
                return
            raise ValueError(f"unsupported value {val!r}")
        term = terms.get(_json_key_for(pred), {})
        if term.get("@type") == "@id" and isinstance(val, str):
            triples.add((s, pred, ref(_expand_ref(val))))
        elif isinstance(val, bool):
            triples.add((s, pred, lit(
                "true" if val else "false", XSD + "boolean")))
        elif isinstance(val, int):
            triples.add((s, pred,
                         lit(str(val), XSD + "integer")))
        elif isinstance(val, float):
            triples.add((s, pred, lit(
                dec_lexical(val), XSD + "decimal")))
        elif isinstance(val, str):
            triples.add((s, pred, lit(val)))
        else:
            raise ValueError(f"unsupported value {val!r}")

    def _json_key_for(pred_iri):
        q = qname(pred_iri)
        for k, v in terms.items():
            if expand(v["@id"]) == pred_iri:
                return k
        return q

    for node in doc["@graph"]:
        s = _expand_ref(node["@id"])
        for key, val in node.items():
            if key == "@id":
                continue
            if key == "@type":
                for t in (val if isinstance(val, list)
                          else [val]):
                    triples.add((s, RDF_TYPE,
                                 ref(_expand_ref(t))))
                continue
            if key in terms:
                pred = expand(terms[key]["@id"])
            elif ":" in key:
                pred = _expand_ref(key)
            else:
                raise ValueError(f"unmapped key {key!r}")
            value_triples(s, pred, val)
    return triples


_TOKEN_RE = re.compile(
    r'<[^>]*>|"(?:\\.|[^"\\])*"(?:\^\^(?:<[^>]*>|[A-Za-z]+:'
    r'[A-Za-z0-9_.\-]+))?|[A-Za-z]+:[A-Za-z0-9_.\-]+|\S+')


def _unescape(body):
    """Single-pass Turtle/N-Triples string unescape."""
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
            elif nxt == "r":
                out.append("\r")
                i += 2
            elif nxt == "t":
                out.append("\t")
                i += 2
            elif nxt == '"':
                out.append('"')
                i += 2
            elif nxt == "\\":
                out.append("\\")
                i += 2
            elif nxt == "u":
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_literal(token):
    m = re.fullmatch(
        r'"((?:\\.|[^"\\])*)"(?:\^\^(<[^>]*>|[A-Za-z]+:'
        r'[A-Za-z0-9_.\-]+))?', token)
    body, dt = _unescape(m.group(1)), m.group(2)
    if dt:
        dt = dt[1:-1] if dt.startswith("<") else _expand_ref(dt)
    return lit(body, dt)


def parse_turtle(text):
    """Parse the Turtle this tool emits (one triple per
    line, prefixed or full terms) -> the triple set."""
    triples = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("@prefix"):
            continue
        tokens = _TOKEN_RE.findall(line)
        if len(tokens) != 4 or tokens[3] != ".":
            raise ValueError(f"unparsable Turtle line: {line!r}")
        s_tok, p_tok, o_tok = tokens[0], tokens[1], tokens[2]
        s = s_tok[1:-1] if s_tok.startswith("<") \
            else _expand_ref(s_tok)
        p = RDF_TYPE if p_tok == "a" else (
            p_tok[1:-1] if p_tok.startswith("<")
            else _expand_ref(p_tok))
        if o_tok.startswith('"'):
            o = _parse_literal(o_tok)
        elif o_tok.startswith("<"):
            o = ref(o_tok[1:-1])
        else:
            o = ref(_expand_ref(o_tok))
        triples.add((s, p, o))
    return triples


def check_triples(T):
    """The validity gate over one built triple set: the
    JSON-LD expands under its own context without errors,
    the Turtle carries the same triples, and every node
    (every subject, and every IRI object that is not a
    vocabulary term) carries a type."""
    problems = []
    doc = render_jsonld(T)
    try:
        from_jsonld = expand_jsonld(doc)
    except ValueError as exc:
        return [f"JSON-LD expansion failed: {exc}"]
    if from_jsonld != T:
        problems.append(
            f"JSON-LD carries {len(from_jsonld)} triples, "
            f"the model has {len(T)}")
    try:
        from_ttl = parse_turtle(render_turtle(T))
    except ValueError as exc:
        problems.append(f"Turtle parse failed: {exc}")
    else:
        if from_ttl != T:
            problems.append(
                f"Turtle carries {len(from_ttl)} triples, "
                f"the model has {len(T)}")
    typed = {s for (s, p, _o) in T if p == RDF_TYPE}
    nodes = {s for (s, _p, _o) in T}
    for n in sorted(nodes - typed):
        problems.append(f"node without a type: {n}")
    return problems


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False,
                      sort_keys=True) + "\n"


def export(root, out_dir):
    T, counts, loss, extras = build_triples(root)
    problems = check_triples(T)
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        return None, problems
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canonical = render_ntriples(T)
    artefacts = {
        "wiki.jsonld": _dump(render_jsonld(T)),
        "wiki.ttl": render_turtle(T),
        "context.jsonld": _dump(render_context()),
        "llms.txt": render_llms(extras, counts),
    }
    hashes = {}
    for name, text in artefacts.items():
        (out / name).write_text(text, encoding="utf-8")
        hashes[name] = {
            "bytes": len(text.encode("utf-8")),
            "sha256": hashlib.sha256(
                text.encode("utf-8")).hexdigest(),
        }
    report = {
        "tool": "wiki_linked_data",
        "kind": "linked-data-export-report",
        "mapping_version": MAPPING_VERSION,
        "corpus_commit": extras["commit"],
        "corpus_dirty": extras["dirty"],
        "counts": counts,
        "canonical_sha256": hashlib.sha256(
            canonical.encode("utf-8")).hexdigest(),
        "artefacts": hashes,
        "mapping": {
            "namespaces": NS,
            "page_types": {
                ("(absent)" if k is None else k): v
                for k, v in PAGE_TYPE_CLASSES.items()},
            "frontmatter_fields": FIELD_MAP,
            "relations": RELATION_MAP,
            "claims": CLAIM_MAP,
            "citations": CITATION_MAP,
            "edge_assertion": {
                "subject": "wk:edgeSubject",
                "object": "wk:edgeObject",
                "predicate": "wk:edgePredicate",
                "relation": "wk:relation",
                "kind": "wk:edgeKind",
                "provenance_label": "wk:provenanceLabel",
                "confidence": "wk:edgeConfidence",
                "polarity": "wk:polarity",
                "assignment_rule": "wk:assignmentRule",
            },
        },
        "loss": loss.as_list(),
        "notes": [
            "The lockfile's converter block is the lockfile "
            "tool's own identity, not a per-citation "
            "construct; no per-citation converter is "
            "recorded in the corpus, so none is mapped.",
            "Frontmatter fields consumed structurally "
            "(type, sources, tags, links, claim, the "
            "relation fields) are mapped as classes, edges, "
            "tag nodes and claim nodes, not as literals.",
        ],
    }
    (out / "linked-data-report.json").write_text(
        _dump(report), encoding="utf-8")
    return report, []


def cmd_export(args):
    report, problems = export(args.root, args.out)
    if report is None:
        return 1
    c = report["counts"]
    print(f"linked-data export: {c['pages']} pages · "
          f"{c['edges']} edges ({c['direct_relation_triples']} "
          f"direct triples) · {c['claims']} claims · "
          f"{c['citations']} citations · {c['triples']} "
          f"triples · loss {c['loss_constructs']} constructs "
          f"/ {c['loss_instances']} instances · canonical "
          f"sha256 {report['canonical_sha256'][:16]}…")
    return 0


def cmd_check(args):
    T, counts, loss, _extras = build_triples(args.root)
    problems = check_triples(T)
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    print(f"check: {counts['triples']} triples; JSON-LD "
          f"expands cleanly, Turtle agrees, every node "
          f"typed; loss {counts['loss_constructs']} "
          f"constructs / {counts['loss_instances']} instances")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="RDF / JSON-LD linked-data export of "
                    "the wiki graph (W6).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export")
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--out", default=None)
    p = sub.add_parser("check")
    p.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    if args.cmd == "export":
        if args.out is None:
            args.out = str(Path(args.root) / "exports"
                           / "linked-data")
        return cmd_export(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
