#!/usr/bin/env python3
"""wiki_schema_extract.py — schema-guided extraction PROPOSALS
at ingest (Marathon R4, lane C).

Pattern: zjunlp/DeepKE / OneKE (MIT) — schema-guided extraction
re-implemented deterministically in our own code, with NO model
calls: a schema fixed in advance (entity types + relation types,
evaluation/extraction-schema.json, or --schema FILE) names what
may be proposed, and this pass scans one source's text and
PROPOSES entities and relations against it. Heuristics only:

  * ATX headings          -> entity candidates (Concept-shaped)
  * [[wikilink]] targets  -> entity candidates (Concept-shaped)
  * capitalised terms     -> entity candidates; a cue word the
    schema attaches to a type (e.g. a title like "Dr") types it
  * a schema relation cue phrase in a sentence with a candidate
    on each side ("X works for Y") -> a relation proposal
  * a [[wikilink]] in a page -> a `mentions` relation proposal,
    when the schema carries that relation type

HONESTY: proposals are never auto-applied. This tool writes
only the proposals artefact it is asked for (plus an optional
report); it never edits the source, never creates or edits a
wiki page, and every artefact carries "applied": false. The
envelope mirrors the gateway's staged-proposal meta shape
(tools/gateway/gateway/store.py: proposal_id, state,
submitted_by, target_path, sha256, bytes, cites, submitted_at —
here submitted_at is the source scan's deterministic stamp,
the source file's own date line when it carries one, else
null) so a reviewer can route it through the same review habit.

    python3 scripts/wiki_schema_extract.py <source>
        [--schema FILE] [--out FILE] [--report FILE] [--root DIR]

Exit codes: 0 ok · 1 refusal · 2 usage error. Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_REL = Path("evaluation/extraction-schema.json")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
CAP_RE = re.compile(
    r"(?<![\w.])(?:([A-Z][a-z]+)\s+)?"
    r"([A-Z][a-zA-Z0-9]*(?:\s+(?:[A-Z][a-zA-Z0-9]*|of|the|and)){0,3})")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
DATE_LINE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})",
                          re.MULTILINE)
STOP_START = {"The", "This", "That", "It", "In", "On", "At",
              "A", "An", "And", "But", "For", "With", "From"}


class ExtractError(Exception):
    pass


def load_schema(path):
    if not Path(path).exists():
        raise ExtractError("schema file missing: %s" % path)
    try:
        schema = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ExtractError("schema is not JSON: %s" % exc)
    if not isinstance(schema.get("entities"), list) \
            or not schema["entities"]:
        raise ExtractError("schema needs a non-empty 'entities' list")
    for ent in schema["entities"]:
        if not ent.get("type"):
            raise ExtractError("every schema entity needs a 'type'")
    for rel in schema.get("relations", []):
        if not rel.get("type"):
            raise ExtractError("every schema relation needs a 'type'")
    return schema


def _entity_types(schema):
    return [e["type"] for e in schema["entities"]]


def _default_type(schema):
    types = _entity_types(schema)
    if schema.get("default_entity_type") in types:
        return schema["default_entity_type"]
    return "Concept" if "Concept" in types else types[0]


def _cue_type(schema, cue):
    if not cue:
        return None
    for ent in schema["entities"]:
        if cue in (ent.get("cues") or []):
            return ent["type"]
    return None


def candidate_terms(text, cues=()):
    """Yield (term, line_no, evidence_kind, cue) deterministically
    in first-appearance order. A preceding capitalised word is
    treated as a cue only when the schema names it as one —
    otherwise it is part of the term ("Northwind Institute",
    not a cue "Northwind" + term "Institute")."""
    cue_words = set(cues)
    seen = {}
    lines = text.splitlines()
    in_fence = False
    for n, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            term = m.group(2).strip().strip("#").strip()
            if term:
                seen.setdefault(term, (n, "heading", None))
        for lm in LINK_RE.finditer(line):
            term = lm.group(1).strip()
            if term:
                seen.setdefault(term, (n, "wikilink", None))
        for cm in CAP_RE.finditer(line):
            term = cm.group(2).strip()
            if cm.group(1) and cm.group(1) not in cue_words:
                term = cm.group(1) + " " + term
            if term.split()[0] in STOP_START and not cm.group(1):
                # A lone sentence-initial capital is not a term;
                # a multiword capitalised run still is.
                if " " not in term:
                    continue
                term = " ".join(term.split()[1:])
                if not term:
                    continue
            seen.setdefault(term, (n, "capitalised-term",
                                   cm.group(1) if cm.group(1)
                                   in cue_words else None))
    return seen


def extract(source_rel, text, schema):
    """The proposals for one source text: {entities, relations}.
    Pure function of (text, schema) — applies nothing."""
    default_type = _default_type(schema)
    all_cues = [c for e in schema["entities"]
                for c in (e.get("cues") or [])]
    terms = candidate_terms(text, all_cues)
    entities = []
    by_term = {}
    for term, (line, kind, cue) in terms.items():
        etype = _cue_type(schema, cue) or (
            default_type if kind in ("heading", "wikilink")
            else _cue_type(schema, cue) or default_type)
        rec = {"name": term, "type": etype, "evidence": kind,
               "line": line, "confidence": "heuristic",
               "source": source_rel}
        entities.append(rec)
        by_term[term.lower()] = rec
    relations = []
    rel_types = {r["type"]: r for r in schema.get("relations", [])}
    # Wikilink mentions.
    if "mentions" in rel_types:
        for n, line in enumerate(text.splitlines(), 1):
            for lm in LINK_RE.finditer(line):
                target = lm.group(1).strip()
                relations.append({
                    "type": "mentions", "subject": source_rel,
                    "object": target, "evidence": "wikilink",
                    "line": n, "confidence": "heuristic",
                    "source": source_rel})
    # Cue-phrase relations inside sentences.
    cue_rels = [(r["type"], [c.lower() for c in
                              (r.get("cue_phrases") or [])])
                for r in schema.get("relations", [])]
    cue_rels = [(t, cues) for t, cues in cue_rels if cues]
    offset = 0
    for line in text.splitlines():
        offset += 1
        for sm in SENTENCE_RE.finditer(line):
            sent = sm.group(0).strip()
            low = sent.lower()
            for rtype, cues in cue_rels:
                for cue in cues:
                    idx = low.find(" " + cue + " ")
                    if idx < 0:
                        continue
                    left = sent[:idx].strip()
                    right = sent[idx + len(cue) + 2:].strip()
                    subj = _best_term(left, by_term)
                    obj = _best_term(right, by_term)
                    if subj and obj and subj is not obj:
                        relations.append({
                            "type": rtype,
                            "subject": subj["name"],
                            "object": obj["name"],
                            "evidence": sent[:200],
                            "line": offset,
                            "confidence": "heuristic",
                            "source": source_rel})
    return {"entities": entities, "relations": relations}


def _best_term(fragment, by_term):
    frag = fragment.lower()
    best = None
    for key, rec in by_term.items():
        if key in frag and (best is None
                             or len(key) > len(best["name"])):
            best = rec
    return best


def build_proposals(root, source, schema_path=None):
    src_path = Path(source)
    if not src_path.is_absolute():
        src_path = Path(root) / source
    if not src_path.is_file():
        raise ExtractError("no such source: %s" % source)
    try:
        rel = src_path.resolve().relative_to(
            Path(root).resolve()).as_posix()
    except ValueError:
        rel = str(source)
    text = src_path.read_text(encoding="utf-8", errors="ignore")
    schema_file = Path(schema_path) if schema_path else \
        Path(root) / DEFAULT_SCHEMA_REL
    schema = load_schema(schema_file)
    found = extract(rel, text, schema)
    data = text.encode("utf-8")
    m = DATE_LINE_RE.search(text)
    return {
        "proposal_id": "prop-extract-" + hashlib.sha256(
            data).hexdigest()[:8],
        "kind": "schema-extraction-proposals",
        "state": "draft",
        "submitted_by": "scripts/wiki_schema_extract.py",
        "session_id": None,
        "task_ref": None,
        "direction_source": {"schema": str(schema_file)},
        "target_path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "cites": [rel],
        "submitted_at": m.group(1) if m else None,
        "applied": False,
        "note": ("PROPOSALS ONLY — generated deterministically "
                 "against a fixed schema; nothing was applied "
                 "to any page and no model was called."),
        "schema_types": {"entities": _entity_types(schema),
                         "relations": [r["type"] for r in
                                       schema.get("relations",
                                                  [])]},
        "proposals": found,
        "counts": {"entities": len(found["entities"]),
                   "relations": len(found["relations"])},
    }


def report_text(payload):
    lines = ["schema extraction proposals for %s"
             % payload["target_path"],
             "state: draft · applied: false (proposals only)",
             "entities proposed: %d" % payload["counts"]["entities"]]
    for e in payload["proposals"]["entities"]:
        lines.append("  - %s [%s] (%s, line %s)"
                     % (e["name"], e["type"], e["evidence"],
                        e["line"]))
    lines.append("relations proposed: %d"
                 % payload["counts"]["relations"])
    for r in payload["proposals"]["relations"]:
        lines.append("  - %s -[%s]-> %s (line %s)"
                     % (r["subject"], r["type"], r["object"],
                        r["line"]))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("--schema", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None,
                    help="proposals JSON path (default: stdout)")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    try:
        payload = build_proposals(args.root, args.source,
                                  args.schema)
    except ExtractError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    blob = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob, encoding="utf-8")
        print("proposals: %s (%d entities, %d relations, "
              "applied: false)"
              % (args.out, payload["counts"]["entities"],
                 payload["counts"]["relations"]))
    else:
        print(blob, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text(payload),
                               encoding="utf-8")
        print("report: %s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
