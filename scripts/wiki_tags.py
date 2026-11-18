#!/usr/bin/env python3
"""wiki_tags.py — the SKOS tag registry (WikiCitadel v1).

Pattern: find 14 (SKOS as the *data model* for the
registered tag vocabulary — one preferred label per concept,
synonyms resolve and never fork, a scope note that says what
the tag means HERE, change notes as the vocabulary's own
changelog) and find 15 (the qSKOS/Skosify check battery
ported, not the SPARQL toolchain: label clashes, asymmetric
relations, tags used but not registered, registered but
never used). The travelling half is find 3's label
*system design* — a closed vocabulary whose meaning rides
the record — transferred in our own vocabulary: the TK/BC
Labels themselves were NOT adopted. The registry is what
lets a tag's meaning travel: scripts/wiki_okf_export.py
carries each exported page's registered prefLabel +
scopeNote under the llm_wiki: namespace, so the meaning
survives the export boundary instead of dying there.

The registry lives at evaluation/tag-registry.jsonl — the
same home as every other governed register in this wiki
(decisions, forecasts, predictions, treatment, source
grades). A wiki page was considered and rejected as the
primary store: a page would be a second, hand-maintained
copy of state that the tooling reads, and the two would
drift; this tool's `resolve` and `check` are the human
views, and the file's header states the maintenance rule.
The page-shaped view, if the owner ever wants one, can be
generated from this file — never the reverse.

Record shape (SKOS field set, our serialisation):

  {kind: "concept", id, prefLabel, altLabels: [],
   hiddenLabels: [], definition, scopeNote,
   broader: [], narrower: [], related: [],
   status: "preferred" | "deprecated",
   replacedBy: <prefLabel>   (deprecated concepts only),
   note, changeNote: ["YYYY-MM-DD: ..."],
   usage: {count, pages: []}  (a seed-time snapshot;
                               check/resolve always recompute
                               live usage from the corpus),
   registered: "YYYY-MM-DD"}

`broader` is the stored relation; `narrower` is stored too
and kept symmetric by `register`/`deprecate` — the check
flags an asymmetric pair if a hand edit breaks the
symmetry (a qSKOS rule). Relations reference concept ids,
and id == prefLabel (labels are already unique slugs).

Commands:

  census            the live tag census over wiki/**.md
  register          add a concept (clashes refused: a
                    string may be the prefLabel of ONE
                    concept and an altLabel of at most one
                    other; relation targets must exist)
  deprecate <label> flip a concept to deprecated, with a
                    replacedBy pointer and a change note
  check             the registry's own lane: unregistered
                    tags in use, deprecated tags still in
                    use, registered-but-never-used concepts,
                    and the qSKOS integrity battery (label
                    clashes, asymmetric or dangling
                    relations). Reports; NEVER rewrites a
                    page or a tag.
  resolve <tag>     the concept record a tag string
                    resolves to (prefLabel or altLabel),
                    with live usage

Exit codes: 0 ok; 1 = check found integrity problems in
the vocabulary itself; 2 = usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_REL = "evaluation/tag-registry.jsonl"
WIKI_REL = "wiki"


# ------------------------------------------------------------ loading

def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", Path(__file__).resolve().parent
        / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VALIDATE = _load_validator()
parse_frontmatter = VALIDATE.parse_frontmatter
as_list = VALIDATE.as_list


def registry_path(root: Path) -> Path:
    return root / REGISTRY_REL


def load_registry(root: Path):
    """(header, [concepts]) — header None when no file."""
    path = registry_path(root)
    if not path.is_file():
        return None, []
    header, concepts = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        elif obj.get("kind") == "concept":
            concepts.append(obj)
    return header, concepts


def save_registry(root: Path, header: dict, concepts: list):
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(header, ensure_ascii=False)]
    for concept in concepts:
        lines.append(json.dumps(concept, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def label_index(concepts: list):
    """pref: {prefLabel -> concept}; any: {label -> concept}
    over prefLabels AND altLabels (first claim wins; clashes
    are the check's business, not the index's)."""
    pref, any_label = {}, {}
    for concept in concepts:
        pref.setdefault(concept["prefLabel"], concept)
        any_label.setdefault(concept["prefLabel"], concept)
        for alt in concept.get("altLabels", []):
            any_label.setdefault(alt, concept)
    return pref, any_label


def resolve_concept(concepts: list, tag: str):
    """(concept, matched_form) or (None, None). matched_form
    is "prefLabel" or "altLabel"."""
    pref, any_label = label_index(concepts)
    if tag in pref:
        return pref[tag], "prefLabel"
    if tag in any_label:
        return any_label[tag], "altLabel"
    return None, None


# ------------------------------------------------------------ census

def census(root: Path) -> dict:
    """The live tag census over wiki/**.md frontmatter."""
    wiki_dir = root / WIKI_REL
    tags = {}
    scanned = tagged = unparsed = 0
    for path in sorted(wiki_dir.rglob("*.md")):
        scanned += 1
        fields, _body = parse_frontmatter(
            path.read_text(encoding="utf-8", errors="replace"))
        if fields is None:
            unparsed += 1
            continue
        page_tags = [str(t) for t in as_list(fields.get("tags"))]
        if page_tags:
            tagged += 1
        rel = path.relative_to(root).as_posix()
        for tag in page_tags:
            entry = tags.setdefault(tag, {"count": 0, "pages": []})
            entry["count"] += 1
            entry["pages"].append(rel)
    return {"pages_scanned": scanned, "pages_tagged": tagged,
            "pages_unparsed": unparsed,
            "distinct_tags": len(tags),
            "total_uses": sum(e["count"] for e in tags.values()),
            "tags": tags}


# ------------------------------------------------------------ check

def check(root: Path) -> dict:
    """The registry's lane. Pure reporting over (registry,
    live census); rewrites nothing."""
    _header, concepts = load_registry(root)
    live = census(root)
    pref, _any = label_index(concepts)

    unregistered = []       # tag strings in use, resolving nowhere
    deprecated_in_use = []  # in use, resolving to a deprecated concept
    for tag, entry in sorted(live["tags"].items()):
        concept, _form = resolve_concept(concepts, tag)
        if concept is None:
            unregistered.append({"tag": tag, **entry})
        elif concept.get("status") == "deprecated":
            deprecated_in_use.append({
                "tag": tag, "concept": concept["prefLabel"],
                "replacedBy": concept.get("replacedBy"),
                **entry})

    used_concepts = set()
    for tag in live["tags"]:
        concept, _form = resolve_concept(concepts, tag)
        if concept is not None:
            used_concepts.add(concept["prefLabel"])
    never_used = sorted(c["prefLabel"] for c in concepts
                        if c["prefLabel"] not in used_concepts)

    # qSKOS-style integrity battery over the vocabulary itself.
    integrity = []
    seen_pref = {}
    for concept in concepts:
        label = concept["prefLabel"]
        if label in seen_pref:
            integrity.append(
                "label clash: %r is the prefLabel of two concepts "
                "(%s, %s)" % (label, seen_pref[label], concept["id"]))
        seen_pref[label] = concept["id"]
    alt_owner = {}
    for concept in concepts:
        for alt in concept.get("altLabels", []):
            if alt in pref and pref[alt]["id"] != concept["id"]:
                integrity.append(
                    "label clash: %r is the altLabel of %s and the "
                    "prefLabel of %s" % (alt, concept["id"], alt))
            if alt in alt_owner and alt_owner[alt] != concept["id"]:
                integrity.append(
                    "label clash: %r is an altLabel of both %s and %s"
                    % (alt, alt_owner[alt], concept["id"]))
            alt_owner[alt] = concept["id"]
            if alt == concept["prefLabel"]:
                integrity.append(
                    "label clash: %r lists itself as its own altLabel"
                    % concept["id"])
    by_id = {c["id"]: c for c in concepts}
    for concept in concepts:
        for rel, inverse in (("broader", "narrower"),
                             ("narrower", "broader"),
                             ("related", "related")):
            for target in concept.get(rel, []):
                if target not in by_id:
                    integrity.append(
                        "dangling relation: %s %s -> %s (no such "
                        "concept)" % (concept["id"], rel, target))
                elif concept["id"] not in by_id[target].get(inverse, []):
                    integrity.append(
                        "asymmetric relation: %s %s -> %s, but %s "
                        "does not list %s under %s"
                        % (concept["id"], rel, target, target,
                           concept["id"], inverse))
        if concept.get("status") == "deprecated" \
                and not concept.get("replacedBy"):
            integrity.append(
                "deprecated concept %s carries no replacedBy pointer"
                % concept["id"])
        if concept.get("status") not in ("preferred", "deprecated"):
            integrity.append(
                "concept %s has unknown status %r"
                % (concept["id"], concept.get("status")))

    return {"concepts": len(concepts),
            "tags_in_use": live["distinct_tags"],
            "total_uses": live["total_uses"],
            "pages_tagged": live["pages_tagged"],
            "unregistered": unregistered,
            "deprecated_in_use": deprecated_in_use,
            "never_used": never_used,
            "integrity": integrity}


# ------------------------------------------------------- OKF travel

def tag_concepts_for(tags: list, concepts: list) -> list:
    """The travelling form of a page's tags: one entry per
    DISTINCT concept the tags resolve to, carrying the
    prefLabel and the scopeNote — the meaning rides along.
    An entry gains `used_as` when the page's literal tag was
    an altLabel, and `status`/`replacedBy` when the concept
    is deprecated. Unregistered tags contribute nothing
    (inventing a meaning for them is the check's opposite;
    `check` reports them)."""
    entries, seen = [], set()
    for tag in tags:
        concept, form = resolve_concept(concepts, str(tag))
        if concept is None or concept["id"] in seen:
            continue
        seen.add(concept["id"])
        entry = {"label": concept["prefLabel"],
                 "scope_note": concept.get("scopeNote", "")}
        if form == "altLabel":
            entry["used_as"] = str(tag)
        if concept.get("status") == "deprecated":
            entry["status"] = "deprecated"
            if concept.get("replacedBy"):
                entry["replacedBy"] = concept["replacedBy"]
        entries.append(entry)
    entries.sort(key=lambda e: e["label"])
    return entries


# ------------------------------------------------------------ commands

def cmd_census(root: Path, as_json: bool) -> int:
    live = census(root)
    if as_json:
        print(json.dumps(live, indent=2, ensure_ascii=False))
        return 0
    print("tag census over %s: %d pages scanned, %d tagged, "
          "%d unparsed" % (WIKI_REL, live["pages_scanned"],
                          live["pages_tagged"],
                          live["pages_unparsed"]))
    print("distinct tags: %d; total uses: %d"
          % (live["distinct_tags"], live["total_uses"]))
    for tag, entry in sorted(
            live["tags"].items(),
            key=lambda kv: (-kv[1]["count"], kv[0])):
        print("  %4d  %s" % (entry["count"], tag))
    return 0


def cmd_register(root: Path, args) -> int:
    header, concepts = load_registry(root)
    if header is None:
        print("error: no registry at %s — seed it first"
              % REGISTRY_REL, file=sys.stderr)
        return 2
    pref, any_label = label_index(concepts)
    label = args.label
    if label in any_label:
        print("error: %r already resolves to concept %s"
              % (label, any_label[label]["id"]), file=sys.stderr)
        return 2
    for alt in args.alt_label or []:
        if alt == label:
            print("error: a concept may not list itself as an "
                  "altLabel", file=sys.stderr)
            return 2
        if alt in any_label:
            print("error: altLabel %r already resolves to "
                  "concept %s" % (alt, any_label[alt]["id"]),
                  file=sys.stderr)
            return 2
    by_id = {c["id"]: c for c in concepts}
    for rel in ("broader", "narrower", "related"):
        for target in getattr(args, rel) or []:
            if target not in by_id:
                print("error: %s target %r is not a registered "
                      "concept (register it first)"
                      % (rel, target), file=sys.stderr)
                return 2
    if args.status == "deprecated" and not args.replaced_by:
        print("error: a deprecated concept needs --replaced-by",
              file=sys.stderr)
        return 2
    if args.replaced_by and args.replaced_by not in pref:
        print("error: --replaced-by %r is not a registered "
              "prefLabel" % args.replaced_by, file=sys.stderr)
        return 2
    today = date.today().isoformat()
    concept = {
        "kind": "concept",
        "id": label,
        "prefLabel": label,
        "altLabels": list(args.alt_label or []),
        "hiddenLabels": list(args.hidden_label or []),
        "definition": args.definition or "",
        "scopeNote": args.scope_note or "",
        "broader": list(args.broader or []),
        "narrower": list(args.narrower or []),
        "related": list(args.related or []),
        "status": args.status,
        "changeNote": ["%s: registered (%s)."
                       % (today, args.change_note or "new concept")],
        "usage": {"count": 0, "pages": []},
        "registered": today,
    }
    if args.note:
        concept["note"] = args.note
    if args.status == "deprecated":
        concept["replacedBy"] = args.replaced_by
    concepts.append(concept)
    # symmetry maintenance: this concept's relations are
    # mirrored on the concepts it points at.
    for target in concept["broader"]:
        by_id[target].setdefault("narrower", []).append(label)
    for target in concept["narrower"]:
        by_id[target].setdefault("broader", []).append(label)
    for target in concept["related"]:
        by_id[target].setdefault("related", []).append(label)
    concepts.sort(key=lambda c: c["prefLabel"])
    save_registry(root, header, concepts)
    print("registered concept %s (status %s; %d concepts total)"
          % (label, args.status, len(concepts)))
    return 0


def cmd_deprecate(root: Path, args) -> int:
    header, concepts = load_registry(root)
    if header is None:
        print("error: no registry at %s" % REGISTRY_REL,
              file=sys.stderr)
        return 2
    pref, _any = label_index(concepts)
    concept, _form = resolve_concept(concepts, args.label)
    if concept is None:
        print("error: %r resolves to no concept" % args.label,
              file=sys.stderr)
        return 2
    if concept.get("status") == "deprecated":
        print("error: %s is already deprecated"
              % concept["prefLabel"], file=sys.stderr)
        return 2
    if args.replaced_by not in pref:
        print("error: --replaced-by %r is not a registered "
              "prefLabel" % args.replaced_by, file=sys.stderr)
        return 2
    if args.replaced_by == concept["prefLabel"]:
        print("error: a concept cannot replace itself",
              file=sys.stderr)
        return 2
    today = date.today().isoformat()
    concept["status"] = "deprecated"
    concept["replacedBy"] = args.replaced_by
    concept.setdefault("changeNote", []).append(
        "%s: deprecated in favour of %s (%s)."
        % (today, args.replaced_by,
           args.change_note or "owner/agent ruling"))
    save_registry(root, header, concepts)
    print("deprecated %s -> replacedBy %s"
          % (concept["prefLabel"], args.replaced_by))
    return 0


def cmd_check(root: Path, as_json: bool) -> int:
    report = check(root)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("tag-registry check (registry: %s)" % REGISTRY_REL)
        print("  concepts registered: %d" % report["concepts"])
        print("  tags in use: %d (%d uses over %d tagged pages)"
              % (report["tags_in_use"], report["total_uses"],
                 report["pages_tagged"]))
        print("  unregistered tags in use: %d"
              % len(report["unregistered"]))
        for item in report["unregistered"]:
            print("    - %r on %d page(s): %s"
                  % (item["tag"], item["count"],
                     ", ".join(item["pages"][:3])
                     + ("…" if len(item["pages"]) > 3 else "")))
        print("  deprecated tags still in use: %d"
              % len(report["deprecated_in_use"]))
        for item in report["deprecated_in_use"]:
            print("    - %r (concept %s, replacedBy %s) on %d "
                  "page(s)" % (item["tag"], item["concept"],
                               item["replacedBy"], item["count"]))
        print("  registered concepts never used: %d"
              % len(report["never_used"]))
        for label in report["never_used"]:
            print("    - %s" % label)
        print("  integrity problems: %d" % len(report["integrity"]))
        for problem in report["integrity"]:
            print("    - %s" % problem)
        print("tag check: concepts %d · in-use %d · unregistered "
              "%d · deprecated-in-use %d · never-used %d · "
              "integrity %d"
              % (report["concepts"], report["tags_in_use"],
                 len(report["unregistered"]),
                 len(report["deprecated_in_use"]),
                 len(report["never_used"]),
                 len(report["integrity"])))
    return 1 if report["integrity"] else 0


def cmd_resolve(root: Path, tag: str) -> int:
    _header, concepts = load_registry(root)
    concept, form = resolve_concept(concepts, tag)
    if concept is None:
        print("%r resolves to no registered concept" % tag)
        return 2
    live = census(root)
    used = set()
    for form_tag in [concept["prefLabel"]] \
            + concept.get("altLabels", []):
        used.update(live["tags"].get(form_tag, {}).get("pages", []))
    out = dict(concept)
    out["resolved_via"] = form
    out["live_usage"] = {"count": len(used), "pages": sorted(used)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="The SKOS tag registry: census, register, "
                    "check, resolve.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("census")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("register")
    p.add_argument("--label", required=True)
    p.add_argument("--alt-label", action="append")
    p.add_argument("--hidden-label", action="append")
    p.add_argument("--broader", action="append")
    p.add_argument("--narrower", action="append")
    p.add_argument("--related", action="append")
    p.add_argument("--definition", default="")
    p.add_argument("--scope-note", default="")
    p.add_argument("--note", default="")
    p.add_argument("--status", default="preferred",
                   choices=["preferred", "deprecated"])
    p.add_argument("--replaced-by", default=None)
    p.add_argument("--change-note", default="")

    p = sub.add_parser("deprecate")
    p.add_argument("label")
    p.add_argument("--replaced-by", required=True)
    p.add_argument("--change-note", default="")

    p = sub.add_parser("check")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("resolve")
    p.add_argument("tag")

    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.command == "census":
        return cmd_census(root, args.json)
    if args.command == "register":
        return cmd_register(root, args)
    if args.command == "deprecate":
        return cmd_deprecate(root, args)
    if args.command == "check":
        return cmd_check(root, args.json)
    if args.command == "resolve":
        return cmd_resolve(root, args.tag)
    return 2


if __name__ == "__main__":
    sys.exit(main())
