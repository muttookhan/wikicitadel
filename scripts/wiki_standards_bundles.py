#!/usr/bin/env python3
"""wiki_standards_bundles.py — the standards bundles pack
(build wave 6, item W6): four small standards bundles over
records this wiki already keeps, each generated read-only
from its source record and each carrying its own gap list.

  1. PROV-DM page-history bundle (prov):
     evaluation/page-history.json — the Round 3 per-page
     git-history data — expressed as W3C PROV: a page is a
     prov:Entity, each recorded commit touching it is a
     prov:Activity that generated a revision prov:Entity
     (specializationOf the page, wasRevisionOf the previous
     revision), and each commit author string is a
     prov:Agent. Serialised as JSON-LD with the house
     context (the PROV terms are the ones the linked-data
     export already uses; this bundle EXTENDS that export's
     provenance side, it does not fork it).

  2. RFC 9264 linkset sidecar (linkset): the traversal
     door's graph — the same labelled edges the Lens and
     the linked-data export read — emitted as an
     application/linkset+json document: one link context
     per anchor page, relation types as URIs (the linked-
     data export's predicate for the relation where the
     closed vocabulary has one, else the wk: vocabulary
     URI for the relation name — RFC 9264 extension
     relation types are URIs), every target resolved
     against the corpus (page / raw / outside-raw) or
     named dangling in the report, never dropped.

  3. UUIDv7 identifier policy (uuid7): RFC 9562 section
     5.7 UUIDv7 as the default for NEW internal identifiers
     minted by wiki tooling, with the minting rule (time-
     ordered, no re-minting, ids never rewritten) and the
     grandfather table for the identifier schemes the
     corpus already carries (cp-NNNNNN checkpoints,
     ocr-NNNN, pred-NNNN, fc-NNNN, weed-NNNN, runtime
     UUIDv4 in WARC records). The policy is PROSPECTIVE:
     it renames nothing that exists. Tooling: mint /
     inspect / validate, with the RFC's own example as a
     test vector.

  4. PREMIS alignment (premis): the PREMIS 3.0 data
     dictionary's object / event / agent / rights
     vocabulary mapped onto the checkpoint + provenance
     fields the wiki already records — DOCUMENTATION AND
     A GENERATED EVENTS VIEW ONLY, no schema migration
     (the Round 13 filing's terms). The events register is
     derived line-by-line from evaluation/checkpoints.jsonl
     (each event names the register line it derives from,
     by that line's hash), plus witness-copy replication
     events where the witness artefact is verified present
     on disk at build time. Actions the records do not
     evidence are NOT asserted; they are gap-list entries.

Licence route: clean re-implementation from the public
standards — W3C PROV-DM / PROV-O (W3C Recommendation
30 April 2013), RFC 9264 (Linkset, IETF), RFC 9562
(UUIDs, section 5.7), PREMIS Data Dictionary 3.0 (Library
of Congress) including its event-type vocabulary. No code
copied from any implementation; the standards are cited
here and in every artefact header.

Grounding + determinism rules (all four bundles):
  - every emitted statement traces to an existing house
    record (the page-history artefact, the door graph,
    the checkpoint register, an on-disk witness artefact);
    each bundle's gap list names what is NOT covered as
    plainly as the report names what is;
  - same corpus + same records -> byte-identical bundles:
    no wall-clock anywhere (the UUIDv7 policy artefact
    carries a fixed all-zero illustrative id, never a
    freshly minted one); datetimes inside bundles are the
    records' own datetimes;
  - read-only over the corpus: artefacts land only in the
    output directory (default exports/standards-bundles/,
    gitignored like the other exports).

Usage:
  python3 scripts/wiki_standards_bundles.py build
      [--root DIR] [--out DIR] [--witness DIR]
  python3 scripts/wiki_standards_bundles.py check
      [--root DIR] [--out DIR] [--witness DIR]
  python3 scripts/wiki_standards_bundles.py uuid7 new
      [--at-ms N]
  python3 scripts/wiki_standards_bundles.py uuid7 inspect ID
Exit 0 on success; check exits 1 on any failed gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import secrets
import subprocess
import sys
import time
import uuid as _uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLES_VERSION = "1.0.0"
DEFAULT_WITNESS = Path.home() / "workspace" / "wiki-checkpoints"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _house(root):
    """The house modules this pack extends (never forks):
    the linked-data export (namespaces, IRI minting, the
    relation->predicate table, corpus state) and the W1.8
    edge-label door."""
    scripts = Path(root) / "scripts"
    ld = _load("wiki_linked_data_for_bundles",
               scripts / "wiki_linked_data.py")
    el = _load("wiki_edge_labels_for_bundles",
               scripts / "wiki_edge_labels.py")
    tv = _load("wiki_traverse_for_bundles",
               scripts / "wiki_traverse.py")
    return ld, el, tv


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(Path(path).read_bytes())


def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False,
                      sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Bundle 1 — PROV-DM page-history bundle
# ---------------------------------------------------------------------------

PROV_MAPPING_VERSION = "1.0.0"

PROV_MAPPING = {
    "compiled page (a key of evaluation/page-history.json)": {
        "prov": "prov:Entity, typed wk:Page",
        "via": "the page IRI the linked-data export mints",
    },
    "one recorded commit in a page's history": {
        "prov": "prov:Activity, typed wk:RevisionActivity; "
                "prov:startedAtTime = prov:endedAtTime = the "
                "commit's recorded date; dcterms:description = "
                "the commit subject; wk:commit = the full sha",
        "via": "evaluation/page-history.json history rows",
    },
    "the page state a commit produced": {
        "prov": "prov:Entity, typed wk:PageRevision; "
                "prov:wasGeneratedBy the activity; "
                "prov:specializationOf the page entity; "
                "prov:wasRevisionOf the previous (older) "
                "revision of the same page, where one is "
                "recorded; prov:generatedAtTime = the "
                "commit's recorded date",
        "via": "one revision entity per history row",
    },
    "a commit author string": {
        "prov": "prov:Agent (the gateway author also "
                "prov:SoftwareAgent); rdfs:label and "
                "wk:authorString carry the string verbatim; "
                "the activity prov:wasAssociatedWith the "
                "agent and the revision prov:wasAttributedTo "
                "the agent",
        "via": "distinct author strings in the artefact",
    },
}

PROV_CONTEXT = {
    "prov": "http://www.w3.org/ns/prov#",
    "wk": "https://wikicitadel.example.org/vocab#",
    "dcterms": "http://purl.org/dc/terms/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-",
                  text.lower()).strip("-") or "unknown"


def _dt(value):
    return {"@value": value, "@type": "xsd:dateTime"}


def build_prov(history, ld):
    """(document, counts, covered_pages) from the parsed
    page-history artefact. Pure: same artefact in, same
    document out. History rows are taken in the artefact's
    own order (git log order, newest first); the revision
    chain links each revision to the next older one."""
    pages = (history or {}).get("pages") or {}
    graph = []
    agents = {}
    n_rev = n_act = 0
    for rel in sorted(pages):
        rows = pages[rel].get("history") or []
        page_iri = ld.iri(rel)
        graph.append({"@id": page_iri,
                      "@type": ["prov:Entity", "wk:Page"],
                      "rdfs:label": rel})
        rev_iris = []
        for row in rows:
            commit = row["commit"]
            author = row.get("author") or "unknown"
            if author not in agents:
                slug = _slug(author)
                types = ["prov:Agent"]
                if slug.startswith("gateway"):
                    types.append("prov:SoftwareAgent")
                agents[author] = {
                    "@id": ld.iri(f"agents/{slug}"),
                    "@type": types,
                    "rdfs:label": author,
                    "wk:authorString": author}
            agent_iri = agents[author]["@id"]
            rev_iri = ld.iri(f"revisions/{commit}/{rel}")
            act_iri = ld.iri(f"activities/{commit}/{rel}")
            rev_iris.append(rev_iri)
            graph.append({
                "@id": act_iri,
                "@type": ["prov:Activity", "wk:RevisionActivity"],
                "prov:startedAtTime": _dt(row["date"]),
                "prov:endedAtTime": _dt(row["date"]),
                "prov:wasAssociatedWith": agent_iri,
                "dcterms:description": row.get("subject") or "",
                "wk:commit": commit})
            graph.append({
                "@id": rev_iri,
                "@type": ["prov:Entity", "wk:PageRevision"],
                "prov:specializationOf": page_iri,
                "prov:wasGeneratedBy": act_iri,
                "prov:wasAttributedTo": agent_iri,
                "prov:generatedAtTime": _dt(row["date"]),
                "wk:commit": commit})
            n_rev += 1
            n_act += 1
        for i in range(len(rev_iris) - 1):
            node = next(g for g in graph if g["@id"] == rev_iris[i])
            node["prov:wasRevisionOf"] = rev_iris[i + 1]
    graph.extend(agents.values())
    graph.sort(key=lambda g: g["@id"])
    doc = {"@context": PROV_CONTEXT, "@graph": graph}
    counts = {"pages": len(pages), "revision_entities": n_rev,
              "activities": n_act, "agents": len(agents),
              "agent_names": sorted(agents)}
    return doc, counts, sorted(pages)


def prov_gaps(all_pages, covered):
    """Compiled pages with no entry in the page-history
    artefact get no PROV statements — named, not smoothed."""
    missing = sorted(set(all_pages) - set(covered))
    return {
        "pages_not_in_page_history_artefact": missing,
        "pages_not_in_page_history_count": len(missing),
        "not_covered": [
            "the capture -> ingest -> compile -> cite -> "
            "correct provenance chain is not serialised as "
            "PROV here: citation/claim provenance lives in "
            "the linked-data export (cito/oa terms, and "
            "prov:wasDerivedFrom for derives-from edges "
            "only), and the corrections ledger (wiki/rules/"
            "corrections-ledger.md) has no PROV serialisation",
            "activity start and end are the same timestamp: "
            "the artefact records one date per commit",
            "revision CONTENT is not carried: the bundle is "
            "metadata about revisions; the bytes are git's "
            "objects, and the artefact's latest_diff field "
            "is not reproduced",
            "agents are the artefact's author strings, "
            "verbatim; no identity resolution beyond the "
            "string is asserted (e.g. two strings for one "
            "actor stay two agents)",
            "renames: the artefact is built with git log "
            "--follow, so a renamed page's history is the "
            "followed history; the bundle asserts nothing "
            "about rename events themselves",
        ],
    }


# ---------------------------------------------------------------------------
# Bundle 2 — RFC 9264 linkset sidecar for the door graph
# ---------------------------------------------------------------------------

LINKSET_MAPPING_VERSION = "1.0.0"


def relation_type_uri(relation, ld):
    """The RFC 9264 relation type for a house relation:
    the linked-data export's predicate for it, expanded,
    where the closed vocabulary maps one; otherwise the
    relation's own wk: vocabulary URI (an RFC 9264
    extension relation type, which the RFC requires to
    be a URI)."""
    mapped = ld.RELATION_MAP.get(relation)
    if mapped:
        return ld.expand(mapped[0])
    return ld.NS["wk"] + relation


def classify_target(dst, kind, pages, root, ld):
    """(href, target_kind) for one door edge target,
    resolved against the corpus itself. target_kind is
    page / raw / outside-raw / dangling — the linked-data
    export's own classification, reused."""
    if dst in pages:
        return ld.iri(dst), "page"
    if kind == "citation":
        bare = dst[4:] if dst.startswith("raw:") else dst
        href, _rel, tkind = ld._target_for_bare(bare, pages,
                                                root)
        return href, tkind
    if (root / dst).is_file():
        return ld.iri(dst), "raw" if dst.startswith("raw/") \
            else "outside-raw"
    if (root / "raw" / dst).is_file():
        return ld.iri("raw/" + dst), "raw"
    return ld.iri("unresolved/" + dst), "dangling"


def build_linkset(edges, pages, root, ld):
    """(document, counts, dangling) — pure over the door's
    labelled edges. One link context per anchor; relation
    keys sorted; targets deduplicated and sorted by href;
    a page target carries its frontmatter title as the
    RFC 9264 "title" attribute where the page states one."""
    by_anchor = {}
    dangling = []
    seen = set()
    dupes = 0
    per_relation = {}
    per_kind = {}
    total = 0
    for e in edges:
        anchor = ld.iri(e["src"])
        rel_uri = relation_type_uri(e["relation"], ld)
        href, tkind = classify_target(e["dst"], e["kind"],
                                        pages, root, ld)
        key = (anchor, rel_uri, href)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        target = {"href": href}
        if tkind == "page":
            fields = (pages.get(e["dst"]) or ({},))[0] or {}
            if fields.get("title"):
                target["title"] = str(fields["title"])
        by_anchor.setdefault(anchor, {}).setdefault(
            rel_uri, []).append(target)
        per_relation[e["relation"]] = \
            per_relation.get(e["relation"], 0) + 1
        per_kind[tkind] = per_kind.get(tkind, 0) + 1
        total += 1
        if tkind == "dangling":
            dangling.append({"anchor": e["src"],
                             "relation": e["relation"],
                             "target_as_written": e["dst"],
                             "href": href})
    linkset = []
    for anchor in sorted(by_anchor):
        item = {"anchor": anchor}
        for rel_uri in sorted(by_anchor[anchor]):
            item[rel_uri] = sorted(by_anchor[anchor][rel_uri],
                                   key=lambda t: t["href"])
        linkset.append(item)
    doc = {"linkset": linkset}
    counts = {"anchors": len(linkset), "links": total,
              "duplicates_collapsed": dupes,
              "per_relation": per_relation,
              "per_target_kind": per_kind,
              "dangling": len(dangling)}
    return doc, counts, sorted(
        dangling, key=lambda d: (d["anchor"], d["relation"],
                                 d["target_as_written"]))


def linkset_gaps():
    return [
        "the linkset carries the door graph's edges only: "
        "citation selectors, line ranges and lock hashes "
        "stay in the citation lockfile and the linked-data "
        "export — the sidecar is the relation index, not "
        "the citation record",
        "W1.8 provenance labels (EXTRACTED / INFERRED / "
        "AMBIGUOUS) and confidences are not carried per "
        "link: RFC 9264's standard target attributes have "
        "no provenance slot, and inventing one would fork "
        "the format; the labels live on the linked-data "
        "export's EdgeAssertion nodes for the same edges",
        "relations with no predicate in the closed "
        "vocabulary (today: exemplifies) are emitted under "
        "their wk: vocabulary URI as RFC 9264 extension "
        "relation types — typed, but with no external "
        "predicate semantics, which the report states",
        "dangling targets are minted under the export's "
        "unresolved/ namespace so the link stays visible "
        "in the sidecar; the namespace names a non-target, "
        "not a fetchable resource",
    ]


# ---------------------------------------------------------------------------
# Bundle 3 — UUIDv7 identifier policy + tooling (RFC 9562)
# ---------------------------------------------------------------------------

UUID7_POLICY_VERSION = "1.0.0"

# The RFC 9562 Appendix A example, as a fixed test vector:
# unix_ts_ms 1645557742000, rand_a 0xCC3,
# rand_b 0x18C4DC0C0C07398F.
UUID7_RFC_VECTOR = (1645557742000, 0xCC3, 0x18C4DC0C0C07398F,
                    "017f22e2-79b0-7cc3-98c4-dc0c0c07398f")
# The all-zero illustrative id used in the policy artefact:
# fixed parts, never a freshly minted id (determinism).
UUID7_ILLUSTRATIVE = "00000000-0000-7000-8000-000000000000"

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_UUID_SEARCH_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def uuid7_from_parts(timestamp_ms, rand_a, rand_b):
    """The RFC 9562 section 5.7 layout, from explicit
    parts (the deterministic core; minting injects
    randomness here)."""
    if not (0 <= timestamp_ms < 1 << 48):
        raise ValueError("timestamp_ms out of 48-bit range")
    if not (0 <= rand_a < 1 << 12):
        raise ValueError("rand_a out of 12-bit range")
    if not (0 <= rand_b < 1 << 62):
        raise ValueError("rand_b out of 62-bit range")
    b = bytearray(16)
    b[0:6] = timestamp_ms.to_bytes(6, "big")
    b[6] = 0x70 | ((rand_a >> 8) & 0x0F)
    b[7] = rand_a & 0xFF
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)
    b[9:16] = (rand_b & ((1 << 56) - 1)).to_bytes(7, "big")
    return str(_uuid.UUID(bytes=bytes(b)))


def mint_uuid7(timestamp_ms=None):
    """A fresh UUIDv7. The only wall-clock reader in this
    module, behind the uuid7 CLI — bundle artefacts never
    carry minted ids."""
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    return uuid7_from_parts(timestamp_ms,
                            secrets.randbits(12),
                            secrets.randbits(62))


def parse_uuid(value):
    """(uuid.UUID | None) for a canonical-shaped string."""
    if not isinstance(value, str) or not _UUID_RE.match(value):
        return None
    try:
        return _uuid.UUID(value)
    except ValueError:
        return None


def uuid7_timestamp_ms(value):
    if not is_uuid7(value):
        raise ValueError(f"not a UUIDv7: {value!r}")
    return int.from_bytes(parse_uuid(value).bytes[0:6], "big")


def is_uuid7(value):
    """Version nibble 7 + the RFC 9562 variant (10xx),
    checked at the bit level — the property the standard
    defines, not a library convenience."""
    u = parse_uuid(value)
    return u is not None and u.bytes[6] >> 4 == 0x7 \
        and u.bytes[8] >> 6 == 0b10


def uuid_version_census(root):
    """The grounded 'current state' for the policy: UUID-
    shaped strings in the evaluation registers, classified
    by version nibble, and the tooling files that mint
    UUIDs today. Static and deterministic."""
    found = {}
    ev = Path(root) / "evaluation"
    if ev.is_dir():
        for path in sorted(ev.glob("*.jsonl")):
            for m in _UUID_SEARCH_RE.finditer(
                    path.read_text(encoding="utf-8",
                                   errors="ignore")):
                u = parse_uuid(m.group(0))
                if u is not None:
                    key = f"v{u.version}"
                    found[key] = found.get(key, 0) + 1
    minters = []
    scripts = Path(root) / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.glob("*.py")):
            text = path.read_text(encoding="utf-8",
                                  errors="ignore")
            if re.search(r"uuid4\s*\(", text):
                minters.append(f"scripts/{path.name}")
    return {"register_uuids_by_version": found,
            "uuid4_minting_files": minters}


UUID7_POLICY = {
    "version": UUID7_POLICY_VERSION,
    "adopted": "2026-10-22",
    "standard": "RFC 9562 section 5.7 (UUIDv7)",
    "default_rule": (
        "Every NEW internal identifier minted by wiki "
        "tooling from adoption forward is a UUIDv7, unless "
        "the object's register already runs a grandfathered "
        "scheme (below), in which case the register's own "
        "scheme continues — one scheme per register, never "
        "two in one register."),
    "minting_rules": [
        "time-ordered: the 48-bit unix millisecond field "
        "makes string order agree with mint order across "
        "milliseconds; identifiers sort by creation without "
        "a separate timestamp column",
        "no re-minting: an identifier, once written to any "
        "register or artefact, is never replaced; a "
        "correction appends a new record naming the old id, "
        "it does not rewrite the id",
        "legacy ids are never rewritten: grandfathered "
        "schemes keep issuing and resolving exactly as "
        "before; no migration, no alias table is created — "
        "each register remains the map for its own ids",
        "an id names the object, not its content: content "
        "identity stays with the house hashes (citation "
        "lockfile line hashes, checkpoint line hashes, "
        "merkle roots), which this policy does not touch",
        "mint through scripts/wiki_standards_bundles.py "
        "uuid7 new (or mint_uuid7 in this module) so the "
        "layout is the RFC's, verified against the RFC's "
        "own example vector in the test suite",
    ],
    "grandfathered_schemes": [
        {"scheme": "cp-NNNNNN", "register":
         "evaluation/checkpoints.jsonl",
         "disposition": "continues; checkpoint ids stay "
                        "sequential and human-citable"},
        {"scheme": "ocr-NNNN", "register":
         "evaluation/ocr-queue.jsonl",
         "disposition": "continues"},
        {"scheme": "pred-NNNN", "register":
         "evaluation/predictions.jsonl",
         "disposition": "continues"},
        {"scheme": "fc-NNNN", "register":
         "forecast ids cited across wiki pages",
         "disposition": "continues"},
        {"scheme": "weed-NNNN", "register":
         "evaluation/weeding-nominations.jsonl",
         "disposition": "continues"},
        {"scheme": "UUIDv4 (runtime-minted)",
         "register": "WARC record ids (scripts/wiki_warc.py, "
                     "scripts/wiki_warc_capture.py)",
         "disposition": "retained for WARC tooling "
                        "interoperability; the ids are "
                        "minted at capture time and stored "
                        "in the WARC records themselves, "
                        "not in a house register"},
    ],
    "out_of_scope": [
        "content hashes (sha256 lock hashes, merkle roots, "
        "canonical export hashes) are identifiers OF "
        "content and are not replaced by UUIDs",
        "page paths and raw paths are the wiki's human "
        "identifiers and stay; the linked-data export's "
        "IRIs are derived from them, not from UUIDs",
        "external identifiers (DOIs, ORCIDs, git SHAs, "
        "message ids from other systems) are recorded as "
        "issued, never re-minted",
        "ephemeral protocol values minted at runtime "
        "(e.g. the multipart boundary in "
        "scripts/wiki_openrefine_trial.py) are not "
        "identifiers of record and are out of scope",
    ],
    "gaps": [
        "adoption is prospective and by convention: no "
        "existing tool is rewritten tonight to mint v7 — "
        "the first register that needs a new non-schemed "
        "identifier is where the default first applies, "
        "and that adoption is recorded when it happens",
        "within one millisecond, string order among v7 "
        "ids is random-tail order, not insertion order "
        "(RFC 9562 makes the same statement); a register "
        "that needs intra-millisecond order keeps its own "
        "sequence field",
    ],
}


def render_uuid7_policy(census):
    """The policy artefact: rendered from UUID7_POLICY +
    the live census, deterministically (the illustrative
    id is the fixed all-zero-parts id, labelled as such)."""
    lines = [
        "# UUIDv7 identifier policy",
        "",
        f"Policy version {UUID7_POLICY['version']}, "
        f"adopted {UUID7_POLICY['adopted']} (build wave 6, "
        "standards bundles pack). Standard: "
        f"{UUID7_POLICY['standard']}. Generated by "
        "scripts/wiki_standards_bundles.py from the policy "
        "table in that module — regenerate, never hand-edit.",
        "",
        "## The default",
        "",
        UUID7_POLICY["default_rule"],
        "",
        "Illustrative UUIDv7 (fixed all-zero parts, shown "
        "for shape only — not a minted id): "
        f"`{UUID7_ILLUSTRATIVE}`",
        "",
        "## Minting rules",
        "",
    ]
    lines += [f"- {r}" for r in UUID7_POLICY["minting_rules"]]
    lines += ["", "## Grandfathered schemes (never rewritten)",
              ""]
    for g in UUID7_POLICY["grandfathered_schemes"]:
        lines.append(f"- `{g['scheme']}` — {g['register']}: "
                     f"{g['disposition']}")
    lines += ["", "## Out of scope", ""]
    lines += [f"- {s}" for s in UUID7_POLICY["out_of_scope"]]
    lines += ["", "## Gaps (stated, not smoothed)", ""]
    lines += [f"- {s}" for s in UUID7_POLICY["gaps"]]
    lines += ["", "## Current state (census at build)", "",
              f"- UUID-shaped strings in evaluation "
              f"registers, by version: "
              f"{json.dumps(census['register_uuids_by_version'], sort_keys=True)}",
              f"- Tooling files that mint UUIDv4 today: "
              f"{', '.join(census['uuid4_minting_files']) or 'none'}",
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bundle 4 — PREMIS alignment + generated preservation events
# ---------------------------------------------------------------------------

PREMIS_MAPPING_VERSION = "1.0.0"

# The alignment table: PREMIS 3.0 semantic units -> the
# house fields that already carry them. Documentation
# only: no house schema changes (the filing's terms).
PREMIS_ALIGNMENT = [
    {"entity": "Object", "premis": "objectIdentifier",
     "house": "repo-relative path (checkpoints.d/<id>.json, "
              "evaluation/merkle-manifest.jsonl, a bag's "
              "payload paths)",
     "notes": "paths are the wiki's object identifiers; "
              "the linked-data export derives IRIs from "
              "them"},
    {"entity": "Object", "premis": "objectCharacteristics / "
                                   "fixity (messageDigest)",
     "house": "checkpoint line_hash + signature; provenance "
              "manifest_sha256 and corpus_root in each "
              "checkpoint line; manifest-sha256.txt inside "
              "a bag",
     "notes": "sha256 throughout, as PREMIS records the "
              "algorithm with the digest"},
    {"entity": "Object", "premis": "preservationLevel / "
                                   "storage",
     "house": "retention-policy.json classes (keep-forever "
              "vs clocked) and the witness copy outside the "
              "repo",
     "notes": "class-level only; no per-object "
              "preservationLevel is recorded — see gaps"},
    {"entity": "Event", "premis": "eventIdentifier",
     "house": "<checkpoint id>/<event slug>, minted by "
              "this generator",
     "notes": "derived identifiers: stable because the "
              "source lines are hash-chained and immutable"},
    {"entity": "Event", "premis": "eventType",
     "house": "derived from the register line kind + the "
              "act it records (creation / fixity check / "
              "replication / timestamp anchor)",
     "notes": "Library of Congress PREMIS event types "
              "where they fit; 'timestamp anchor' is a "
              "named local extension"},
    {"entity": "Event", "premis": "eventDateTime",
     "house": "created_utc (checkpoint lines) / "
              "attempted_utc (anchor lines)",
     "notes": "the record's own datetime, never the "
              "generator's clock"},
    {"entity": "Event", "premis": "eventOutcomeInformation",
     "house": "anchor entries' recorded status, verbatim "
              "(a failed anchor stays failed); signature "
              "presence for checkpoint creation",
     "notes": "outcomes are copied, never upgraded — the "
              "schema's dual-anchor rule in PREMIS dress"},
    {"entity": "Event", "premis": "linkingAgentIdentifier",
     "house": "signer identity on checkpoint lines "
              "(mehmed@llm-wiki); scripts/wiki_checkpoint.py "
              "for the acts the tool performs (anchoring, "
              "witness copy)",
     "notes": "the register records the identity string; "
              "agentType is not recorded there — see gaps"},
    {"entity": "Event", "premis": "linkingObjectIdentifier",
     "house": "the checkpoint artefact / the provenance "
              "manifest the checkpoint binds",
     "notes": "every event also names its source register "
              "line by line_hash (the derivation audit "
              "trail, a house field riding beside PREMIS)"},
    {"entity": "Agent", "premis": "agentIdentifier / "
                                   "agentName / agentType",
     "house": "signer identity string; the checkpoint "
              "tool as software agent for its own acts",
     "notes": "no agent register exists; identity is the "
              "string on the signed lines"},
    {"entity": "Rights", "premis": "rightsStatement "
                                   "(rightsBasis, "
                                   "rightsGranted)",
     "house": "retention-policy.json classes (how long, "
              "what act an expiry names) + sensitivity.json "
              "classes (who may read/cite)",
     "notes": "policy-level mapping only: no per-object "
              "rights statements are recorded — see gaps"},
]

PREMIS_EVENT_TYPES = {
    "creation": "LoC PREMIS event type",
    "fixity check": "LoC PREMIS event type",
    "replication": "LoC PREMIS event type",
    "timestamp anchor": "local extension (the schema's "
                        "dual-anchor rule)",
}


def build_premis_events(register_rows, witness_ids):
    """(events, counts) derived line-by-line from the
    parsed checkpoints register. Pure. An event exists
    only where a register line (or, for replication, a
    register line + a verified witness artefact) grounds
    it."""
    events = []
    counts = {"header_lines": 0, "checkpoint_lines": 0,
              "anchor_lines": 0, "events": 0,
              "by_type": {}, "by_outcome": {}}
    for row in register_rows:
        kind = row.get("kind")
        if kind == "header":
            counts["header_lines"] += 1
            continue
        if kind == "checkpoint":
            counts["checkpoint_lines"] += 1
            cid = row["id"]
            obj = f"evaluation/checkpoints.d/{cid}.json"
            prov = row.get("provenance") or {}
            events.append({
                "eventIdentifier": f"{cid}/creation",
                "eventType": "creation",
                "eventDateTime": row["created_utc"],
                "eventOutcome": "success",
                "eventDetail": "signed checkpoint created; "
                               f"binds git HEAD "
                               f"{row.get('git_head')} and "
                               f"provenance corpus root "
                               f"{prov.get('corpus_root')}",
                "linkingAgent": row.get("signer"),
                "linkingObject": obj,
                "sourceLineHash": row.get("line_hash")})
            events.append({
                "eventIdentifier": f"{cid}/fixity-check",
                "eventType": "fixity check",
                "eventDateTime": row["created_utc"],
                "eventOutcome": "success",
                "eventDetail": "checkpoint binds the "
                               "provenance manifest as "
                               f"recorded: {prov.get('manifest')} "
                               f"sha256 {prov.get('manifest_sha256')}, "
                               f"{prov.get('sources')} sources, "
                               f"corpus root "
                               f"{prov.get('corpus_root')}",
                "linkingAgent": row.get("signer"),
                "linkingObject": prov.get("manifest"),
                "sourceLineHash": row.get("line_hash")})
            if cid in witness_ids:
                events.append({
                    "eventIdentifier": f"{cid}/replication",
                    "eventType": "replication",
                    "eventDateTime": row["created_utc"],
                    "eventOutcome": "success",
                    "eventDetail": "witness copy of the "
                                   "checkpoint artefact "
                                   "verified present outside "
                                   "the repo at bundle build "
                                   "(the copy is made by the "
                                   "create act, per "
                                   "scripts/wiki_checkpoint.py)",
                    "linkingAgent": "scripts/wiki_checkpoint.py",
                    "linkingObject": obj,
                    "sourceLineHash": row.get("line_hash")})
        elif kind == "anchor":
            counts["anchor_lines"] += 1
            cid = row.get("checkpoint")
            for entry in row.get("anchors") or []:
                mech = entry.get("mechanism")
                events.append({
                    "eventIdentifier": f"{cid}/anchor-{mech}",
                    "eventType": "timestamp anchor",
                    "eventDateTime": row.get("attempted_utc"),
                    "eventOutcome": entry.get("status"),
                    "eventDetail": f"{mech}: "
                                   f"{entry.get('detail')}",
                    "linkingAgent": "scripts/wiki_checkpoint.py",
                    "linkingObject":
                        f"evaluation/checkpoints.d/{cid}.json",
                    "sourceLineHash": row.get("line_hash")})
    events.sort(key=lambda e: (e["eventDateTime"],
                               e["eventIdentifier"]))
    counts["events"] = len(events)
    for e in events:
        counts["by_type"][e["eventType"]] = \
            counts["by_type"].get(e["eventType"], 0) + 1
        counts["by_outcome"][str(e["eventOutcome"])] = \
            counts["by_outcome"].get(str(e["eventOutcome"]),
                                      0) + 1
    return events, counts


def premis_gaps(register_rows, witness_ids, root):
    """What the records do not evidence — named, never
    asserted as events."""
    cps = [r["id"] for r in register_rows
           if r.get("kind") == "checkpoint"]
    unwitnessed = [c for c in cps if c not in witness_ids]
    gaps = [
        "verification runs: evaluation/reverify-history"
        ".jsonl is an empty register (0 bytes) — no "
        "verification event exists on the record to align, "
        "so none is asserted here",
        "erasures: evaluation/erasure-certificates.jsonl "
        "is an empty register (0 bytes) — no erasure event "
        "is asserted",
        "bagging: scripts/wiki_bag.py (BagIt, RFC 8493) "
        "exists, but no bag artefact (bag-info.txt) stands "
        "in the tree, so no bagging event is asserted; the "
        "nightly Drive zip is a different route whose "
        "records live in goal state outside this tree and "
        "is likewise not asserted here",
        "rights: the alignment maps retention + "
        "sensitivity CLASSES to PREMIS rights terms; no "
        "per-object rights statement is recorded anywhere "
        "in the wiki, so none is emitted",
        "agents: the checkpoint register records the "
        "signer identity string only; PREMIS agentType "
        "(person / organization / software) is not on the "
        "record for the signer and is not invented here — "
        "only the tool's own acts name it, as software, by "
        "construction",
        "preservationLevel is class-level (retention "
        "policy), never per-object, in the house records",
    ]
    if unwitnessed:
        gaps.append("checkpoints with no witness artefact "
                    "found at build (no replication event "
                    "asserted for them): "
                    + ", ".join(unwitnessed))
    return gaps


def render_premis_alignment():
    lines = [
        "# PREMIS alignment — checkpoint + provenance "
        "vocabulary",
        "",
        f"Alignment version {PREMIS_MAPPING_VERSION}. "
        "PREMIS Data Dictionary 3.0 (Library of Congress) "
        "terms mapped onto the fields this wiki already "
        "records. DOCUMENTATION ONLY — no house schema is "
        "changed by this alignment (the Round 13 filing's "
        "terms). Generated by scripts/wiki_standards_"
        "bundles.py from the alignment table in that "
        "module — regenerate, never hand-edit.",
        "",
        "| PREMIS entity | Semantic unit | House field | "
        "Notes |",
        "|---|---|---|---|",
    ]
    for row in PREMIS_ALIGNMENT:
        lines.append(f"| {row['entity']} | {row['premis']} "
                     f"| {row['house']} | {row['notes']} |")
    lines += ["", "## Event-type vocabulary", ""]
    for t, origin in sorted(PREMIS_EVENT_TYPES.items()):
        lines.append(f"- `{t}` — {origin}")
    lines += ["",
              "The generated events view is "
              "premis-events.jsonl beside this file: one "
              "PREMIS-shaped event per grounded act, each "
              "naming the checkpoint register line it "
              "derives from (sourceLineHash).",
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration — build all four bundles from the records
# ---------------------------------------------------------------------------

ARTEFACTS = ["page-history-prov.jsonld", "citation-linkset.json",
             "uuidv7-policy.md", "premis-alignment.md",
             "premis-events.jsonl",
             "standards-bundles-report.json"]


def _read_jsonl(path):
    rows = []
    if Path(path).is_file():
        for line in Path(path).read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _witness_ids(witness_dir):
    d = Path(witness_dir) / "checkpoints.d"
    if not d.is_dir():
        return set()
    return {p.name[:-5] for p in d.glob("*.json")}


def build_all(root, witness_dir):
    """{artefact_name: text} + the report object. Reads
    the corpus read-only; writes nothing."""
    root = Path(root)
    ld, el, tv = _house(root)
    commit, dirty = ld.corpus_commit(root)

    # Bundle 1 — PROV over the page-history artefact.
    ph_path = root / "evaluation" / "page-history.json"
    history = json.loads(ph_path.read_text(encoding="utf-8")) \
        if ph_path.is_file() else {"pages": {}}
    prov_doc, prov_counts, covered = build_prov(history, ld)
    all_pages = sorted(
        str(p.relative_to(root))
        for p in (root / "wiki").rglob("*.md")) \
        if (root / "wiki").is_dir() else []
    p_gaps = prov_gaps(all_pages, covered)

    # Bundle 2 — linkset over the door's labelled graph.
    edges, _conflicts = el.labelled_edges(root)
    pages, _keys, _door = tv.page_graph(root)
    ls_doc, ls_counts, ls_dangling = build_linkset(
        edges, pages, root, ld)

    # Bundle 3 — UUIDv7 policy + live census.
    census = uuid_version_census(root)
    policy_text = render_uuid7_policy(census)

    # Bundle 4 — PREMIS events from the checkpoint register.
    reg_path = root / "evaluation" / "checkpoints.jsonl"
    rows = _read_jsonl(reg_path)
    wids = _witness_ids(witness_dir)
    events, premis_counts = build_premis_events(rows, wids)
    header = {
        "kind": "premis-events",
        "version": PREMIS_MAPPING_VERSION,
        "derived_from": "evaluation/checkpoints.jsonl",
        "source_register_sha256": _sha256_file(reg_path)
        if reg_path.is_file() else None,
        "basis": "one event per grounded act on the "
                 "register; each event names its source "
                 "line (sourceLineHash). Replication events "
                 "additionally require the witness artefact "
                 "verified present at build. Ungrounded "
                 "acts are gap-list entries in the report, "
                 "never events.",
    }
    events_text = "".join(
        json.dumps(o, ensure_ascii=False, sort_keys=True)
        + "\n" for o in [header] + events)

    artefacts = {
        "page-history-prov.jsonld": _dump(prov_doc),
        "citation-linkset.json": _dump(ls_doc),
        "uuidv7-policy.md": policy_text,
        "premis-alignment.md": render_premis_alignment(),
        "premis-events.jsonl": events_text,
    }
    report = {
        "kind": "standards-bundles-report",
        "bundles_version": BUNDLES_VERSION,
        "corpus": {"commit": commit, "dirty": dirty},
        "inputs": {
            "page_history": {
                "path": "evaluation/page-history.json",
                "sha256": _sha256_file(ph_path)
                if ph_path.is_file() else None},
            "checkpoints_register": {
                "path": "evaluation/checkpoints.jsonl",
                "sha256": _sha256_file(reg_path)
                if reg_path.is_file() else None},
            "witness_dir": str(witness_dir),
        },
        "bundles": {
            "prov": {"mapping_version": PROV_MAPPING_VERSION,
                     "counts": prov_counts,
                     "mapping": PROV_MAPPING,
                     "gaps": p_gaps},
            "linkset": {
                "mapping_version": LINKSET_MAPPING_VERSION,
                "media_type": "application/linkset+json",
                "counts": ls_counts,
                "dangling": ls_dangling,
                "gaps": linkset_gaps()},
            "uuid7": {"policy_version": UUID7_POLICY_VERSION,
                      "policy": UUID7_POLICY,
                      "census": census,
                      "rfc_vector": UUID7_RFC_VECTOR[3]},
            "premis": {"mapping_version":
                       PREMIS_MAPPING_VERSION,
                       "counts": premis_counts,
                       "alignment": PREMIS_ALIGNMENT,
                       "event_types": PREMIS_EVENT_TYPES,
                       "gaps": premis_gaps(rows, wids, root)},
        },
        "artefacts": {name: _sha256_bytes(text.encode("utf-8"))
                      for name, text in artefacts.items()},
        "artefact_note": "hashes cover the five generated "
                         "artefacts; this report is not "
                         "hashed into itself",
    }
    artefacts["standards-bundles-report.json"] = _dump(report)
    return artefacts, report


def gate_prov(doc):
    ids = {g["@id"] for g in doc["@graph"]}
    refs = ("prov:wasGeneratedBy", "prov:wasAssociatedWith",
            "prov:wasAttributedTo", "prov:specializationOf",
            "prov:wasRevisionOf")
    bad = []
    for g in doc["@graph"]:
        for k in refs:
            v = g.get(k)
            if v is not None and v not in ids:
                bad.append((g["@id"], k, v))
    return (not bad), f"{len(ids)} nodes, {len(bad)} dangling refs"


def gate_linkset(doc, dangling):
    items = doc.get("linkset")
    if not isinstance(items, list):
        return False, "no linkset list"
    n = 0
    for item in items:
        if not str(item.get("anchor", "")).startswith(
                "https://wikicitadel.example.org/"):
            return False, f"bad anchor {item.get('anchor')}"
        for k, v in item.items():
            if k == "anchor":
                continue
            if not isinstance(v, list) or not all(
                    isinstance(t, dict) and "href" in t
                    for t in v):
                return False, f"bad link target list at {k}"
            n += len(v)
    return True, f"{len(items)} anchors, {n} links, " \
                 f"{len(dangling)} dangling named"


def gate_uuid7():
    ms, ra, rb, expect = UUID7_RFC_VECTOR
    if uuid7_from_parts(ms, ra, rb) != expect:
        return False, "RFC 9562 vector mismatch"
    if uuid7_from_parts(0, 0, 0) != UUID7_ILLUSTRATIVE:
        return False, "illustrative id mismatch"
    ids = [uuid7_from_parts(1700000000000 + i, 5, 9)
           for i in range(50)]
    if ids != sorted(ids):
        return False, "string order != time order"
    if not all(is_uuid7(i) for i in ids):
        return False, "minted id fails is_uuid7"
    if uuid7_timestamp_ms(ids[7]) != 1700000000007:
        return False, "timestamp round-trip failed"
    if is_uuid7("00000000-0000-4000-8000-000000000000"):
        return False, "a v4 id passed as v7"
    return True, "RFC vector + ordering + round-trip ok"


def gate_premis(events, rows):
    hashes = {r.get("line_hash") for r in rows
              if r.get("kind") != "header"}
    bad = [e["eventIdentifier"] for e in events
           if e["sourceLineHash"] not in hashes]
    if bad:
        return False, f"ungrounded events: {bad}"
    anchors = {}
    for r in rows:
        if r.get("kind") == "anchor":
            for entry in r.get("anchors") or []:
                anchors[(r["checkpoint"],
                         entry["mechanism"])] = entry["status"]
    for e in events:
        if e["eventType"] == "timestamp anchor":
            cid, mech = e["eventIdentifier"].split(
                "/anchor-", 1)
            if anchors.get((cid, mech)) != e["eventOutcome"]:
                return False, \
                    f"anchor outcome altered: {e['eventIdentifier']}"
    need = {r["id"] for r in rows if r.get("kind") == "checkpoint"}
    have = {e["eventIdentifier"].split("/")[0] for e in events
            if e["eventType"] == "creation"}
    if need != have:
        return False, f"checkpoints without creation events: " \
                      f"{sorted(need - have)}"
    return True, f"{len(events)} events, all grounded in " \
                 f"{len(hashes)} register lines"


def run_check(root, out_dir, witness_dir):
    artefacts, report = build_all(root, witness_dir)
    rows = _read_jsonl(Path(root) / "evaluation"
                       / "checkpoints.jsonl")
    events = [json.loads(l) for l in
              artefacts["premis-events.jsonl"].splitlines()[1:]
              if l.strip()]
    results = []
    ok, detail = gate_prov(json.loads(
        artefacts["page-history-prov.jsonld"]))
    results.append(("prov referential integrity", ok, detail))
    ok, detail = gate_linkset(
        json.loads(artefacts["citation-linkset.json"]),
        report["bundles"]["linkset"]["dangling"])
    results.append(("linkset structure (RFC 9264)", ok, detail))
    ok, detail = gate_uuid7()
    results.append(("uuidv7 (RFC 9562)", ok, detail))
    ok, detail = gate_premis(events, rows)
    results.append(("premis grounding", ok, detail))
    out = Path(out_dir)
    if out.is_dir():
        drift = []
        for name, text in artefacts.items():
            f = out / name
            if not f.is_file():
                drift.append(f"{name}: missing")
            elif f.read_text(encoding="utf-8") != text:
                drift.append(f"{name}: differs")
        results.append(("on-disk artefacts current",
                        not drift, "; ".join(drift) or
                        "all six byte-identical to a rebuild"))
    return all(r[1] for r in results), results


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Standards bundles pack (PROV-DM, "
                    "RFC 9264 linkset, UUIDv7, PREMIS).")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None,
                    help="output dir (default: "
                         "<root>/exports/standards-bundles)")
    ap.add_argument("--witness", default=str(DEFAULT_WITNESS),
                    help="witness dir holding checkpoints.d "
                         "(default: ~/workspace/wiki-"
                         "checkpoints)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    u = sub.add_parser("uuid7")
    usub = u.add_subparsers(dest="ucmd", required=True)
    un = usub.add_parser("new")
    un.add_argument("--at-ms", type=int, default=None)
    ui = usub.add_parser("inspect")
    ui.add_argument("id")
    a = ap.parse_args(argv)
    root = Path(a.root)
    out = Path(a.out) if a.out else \
        root / "exports" / "standards-bundles"
    witness = Path(a.witness)
    if a.cmd == "uuid7":
        if a.ucmd == "new":
            print(mint_uuid7(a.at_ms))
            return 0
        u = parse_uuid(a.id)
        info = {"id": a.id, "valid_uuid": u is not None}
        if u is not None:
            info["version"] = u.version
            info["variant"] = str(u.variant)
            info["is_uuid7"] = is_uuid7(a.id)
            if u.version == 7:
                info["timestamp_ms"] = uuid7_timestamp_ms(a.id)
        print(_dump(info), end="")
        return 0 if u is not None else 1
    if a.cmd == "build":
        artefacts, report = build_all(root, witness)
        out.mkdir(parents=True, exist_ok=True)
        for name, text in artefacts.items():
            (out / name).write_text(text, encoding="utf-8")
        summary = {k: v.get("counts")
                   for k, v in report["bundles"].items()}
        print(_dump({"built": sorted(artefacts),
                     "out": str(out), "counts": summary}),
              end="")
        return 0
    ok, results = run_check(root, out, witness)
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}: "
              f"{detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
