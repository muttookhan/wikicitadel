#!/usr/bin/env python3
"""wiki_export.py — standard exports of the compiled layer.

15-gap item 10 (standard exports) plus the Marp slice of item
15 (multimodal / generative outputs), built 2026-10-20. Three
interchange artefacts over ONE graph, so the formats can never
disagree about what the corpus contains:

  jsonld   The corpus as JSON-LD: every compiled page is a node
           (@id = repo-relative path, title, type, tags, stage,
           status) and every typed wikilink / declared relation
           is a relation entry on its source node, using the
           wiki's relation vocabulary
           (wiki/rules/relation-vocabulary.md, plus the lenslib
           heading types and the adopted `grounds` extension)
           where typed, and `mentions` for untyped links.
  graphml  The same nodes and edges as GraphML XML, parseable
           by xml.etree (nodes carry title/type/status/stage/
           tags/tombstoned data; edges carry a relation data).
  marp     A Marp slide deck for one page (--page) or several
           (--pages a,b,...): `marp: true` frontmatter, a title
           slide, then one slide per page — the page's title as
           its heading, a faithful short excerpt of its own
           body, and its source citations listed. Nothing is
           paraphrased or invented: excerpts are the page's own
           text, truncated only at a word boundary.

Tombstoned pages are EXPORTED, never silently dropped: their
node keeps status "tombstoned", carries "tombstoned": true,
and, where the page records them, its tombstone date, reason
and replacement — the withdrawn state is visible in the
export exactly as it is on the page.

The compiled layer is the OKF export's set (scripts/
wiki_okf_export.py, whose loader this tool reuses by import):
wiki/**/*.md minus wiki/access/ and wiki/talk/ (ledgers and
dispute records, not concepts) minus the structural index.md
and log.md at the wiki root.

Page loading reuses scripts/wiki_validate.py's
parse_frontmatter / as_list by import (the codebase's loader,
not a re-implementation). Typed wikilinks reuse the Lens's
own extractor (tools/lens/lenslib.py extract_wikilinks_typed,
imported in-process like scripts/wiki_traverse.py does) so
this door and the Lens walk the same typed edges; when
lenslib cannot be loaded (it needs PyYAML, the repo's
declared tooling dependency), a stdlib fallback applies the
same SECTION_TYPE_RULES table, reproduced below, so the tool
itself stays stdlib-only and offline.

Frontmatter relation declarations are edges too, in the
vocabulary's own directional spellings: forward fields
(supersedes, cites, corrects, extends, contradicts,
derives_from, replaces_part_of, grounds) assert
source -[term]-> target; inverse fields (superseded_by and
replaced_by, cited_by, corrected_by, is_grounded_by) assert
source -[is-...-by]-> target. The `sources:` field is NOT an
edge here: it is the page->raw-source cites relation, its
targets are not page nodes, and it travels on the node itself
as `sources`, verbatim. A `links:` frontmatter declaration
(the Lens's edge table reads it) contributes its declared
relations verbatim when lenslib's full YAML parse is
available.

Usage:
    python3 scripts/wiki_export.py [--root DIR] jsonld [--out FILE]
    python3 scripts/wiki_export.py [--root DIR] graphml [--out FILE]
    python3 scripts/wiki_export.py [--root DIR] marp \\
        (--page <id> | --pages <id,id,...>) [--out FILE]

Default out is stdout. --root may also be given after the
subcommand. Exit codes: 0 ok · 1 no such page · 2 usage error.

Stdlib only, offline.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

EXCLUDED_DIRS = {"access", "talk"}
STRUCTURAL = {"index.md", "log.md"}  # relative to wiki/ root

GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"

# Relation terms that may appear as a JSON-LD property / a
# GraphML edge relation in this export: the closed vocabulary
# (wiki/rules/relation-vocabulary.md, incl. its inverses and
# the adopted grounds extension), the lenslib heading types,
# and the untyped default.
RELATION_TERMS = (
    "supersedes", "is-superseded-by", "cites", "is-cited-by",
    "corrects", "is-corrected-by", "extends", "contradicts",
    "derives-from", "replaces-part-of", "grounds",
    "is-grounded-by", "exemplifies", "mentions",
)

FORWARD_FIELDS = {
    "supersedes": "supersedes", "cites": "cites",
    "corrects": "corrects", "extends": "extends",
    "contradicts": "contradicts", "derives_from": "derives-from",
    "replaces_part_of": "replaces-part-of", "grounds": "grounds",
}
INVERSE_FIELDS = {
    # field -> vocabulary term asserted in the declared
    # direction (declaring page -> named page)
    "superseded_by": "is-superseded-by",
    "replaced_by": "is-superseded-by",
    "cited_by": "is-cited-by",
    "corrected_by": "is-corrected-by",
    "is_grounded_by": "is-grounded-by",
    "grounded_by": "is-grounded-by",
}

CITE_MARKER_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)")


# ------------------------------------------------------------ loaders

def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _validate_mod():
    return _load_module("wiki_validate", SCRIPTS / "wiki_validate.py")


def _lenslib_mod():
    """The Lens's shared library, or None when it cannot be
    loaded (e.g. PyYAML absent) — the fallback extractor below
    then applies the same heading rules."""
    path = SCRIPTS.parent / "tools" / "lens" / "lenslib.py"
    if not path.is_file():
        return None
    try:
        return _load_module("lenslib", path)
    except Exception:
        return None


_WV = _validate_mod()
parse_frontmatter = _WV.parse_frontmatter
as_list = _WV.as_list
LENSLIB = _lenslib_mod()


# ------------------------------------------- fallback typed extraction
# lenslib's SECTION_TYPE_RULES, reproduced so the fallback
# types links exactly as the Lens does when lenslib itself
# cannot be imported. lenslib remains the primary path.

_FALLBACK_RULES = (
    ("contradicts", ("contradict", "conflict", "disagree", "dispute",
                     "contested", "tension")),
    ("supersedes", ("supersede", "replaces", "replaced by",
                    "deprecated", "obsolete", "retired")),
    ("grounds", ("evidence", "ground", "basis", "provenance",
                 "citation", "sources")),
    ("exemplifies", ("example", "exemplif", "illustrat", "case study",
                     "instance")),
    ("extends", ("extend", "extens", "elaborat", "builds on",
                 "built on", "expansion", "follow-up", "followup")),
)
_FALLBACK_WIKILINK_RE = re.compile(
    r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")
_FALLBACK_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _fallback_link_type(heading):
    if not heading:
        return "mentions"
    h = heading.lower()
    for ltype, keywords in _FALLBACK_RULES:
        if any(re.search(r"\b" + re.escape(k), h) for k in keywords):
            return ltype
    return "mentions"


def _fallback_typed_links(body):
    """lenslib.extract_wikilinks_typed's contract, stdlib only:
    [(target, anchor, label, heading, link_type)] in body order,
    fenced code and inline code spans excluded."""
    out = []
    in_code = False
    heading = None
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        hm = _FALLBACK_HEADING_RE.match(line)
        if hm:
            heading = re.sub(r"\*\*|`", "", hm.group(2)).strip()
        stripped = re.sub(r"`[^`\n]*`", "", line)
        for m in _FALLBACK_WIKILINK_RE.finditer(stripped):
            target = m.group(1).strip()
            out.append((target, m.group(2),
                        (m.group(3) or m.group(1)).strip(),
                        heading, _fallback_link_type(heading)))
    return out


def typed_links(body):
    if LENSLIB is not None:
        return LENSLIB.extract_wikilinks_typed(body)
    return _fallback_typed_links(body)


# ------------------------------------------------------------ the graph

def page_paths(root: Path):
    """Wiki-relative paths of the compiled layer, in the OKF
    export's set (access/ and talk/ excluded, the structural
    index.md / log.md at the wiki root excluded)."""
    wiki = root / "wiki"
    if not wiki.is_dir():
        return []
    out = []
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki)
        if rel.parts[0] in EXCLUDED_DIRS:
            continue
        if len(rel.parts) == 1 and rel.name in STRUCTURAL:
            continue
        out.append(rel)
    return out


def load_pages(root: Path):
    """(pages, keys). pages: {repo-relative rel: record} in
    sorted path order; a record carries fields/body plus the
    derived title and tombstone flag. keys: the resolution
    table (repo path, path without suffix, wiki-relative path,
    stem, title) -> repo-relative rel, first registration
    wins, pages in sorted order."""
    wiki = root / "wiki"
    pages = {}
    keys = {}
    for rel in page_paths(root):
        path = wiki / rel
        text = path.read_text(encoding="utf-8", errors="ignore")
        fields, body = parse_frontmatter(text)
        fields = fields or {}
        # The validator's subset parser nulls nested mappings,
        # so `links:` declarations are taken from the Lens's
        # full YAML parse when it is available (wiki_traverse.py
        # does the same, for the same reason).
        if LENSLIB is not None:
            yaml_fm, _b, _t = LENSLIB.parse_markdown_file(path)
            if isinstance(yaml_fm.get("links"), dict):
                fields = dict(fields)
                fields["links"] = yaml_fm["links"]
        repo_rel = "wiki/" + rel.as_posix()
        title = str(fields.get("title") or "").strip() or rel.stem
        pages[repo_rel] = {
            "id": repo_rel, "fields": fields, "body": body,
            "title": title,
            "tombstoned": str(fields.get("status") or "").strip()
            == "tombstoned",
        }
        for key in (repo_rel, repo_rel[:-3], rel.as_posix(),
                    rel.as_posix()[:-3], rel.stem, title):
            keys.setdefault(key, repo_rel)
    return pages, keys


def resolve_page(keys, name):
    """A page id (as given to marp --page/--pages) -> repo rel,
    or None. Tries the name verbatim, without .md, its
    basename and its stem."""
    name = str(name).strip()
    for cand in (name, name[:-3] if name.endswith(".md") else name,
                 Path(name).name, Path(name).stem):
        if cand in keys:
            return keys[cand]
    return None


def _resolve_link(keys, target):
    for cand in (target, Path(target).name, Path(target).stem):
        if cand in keys:
            return keys[cand]
    return None


def build_graph(root: Path):
    """(pages, keys, edges): edges are {source, target,
    relation} dicts between page nodes, deduplicated and
    deterministically sorted — the ONE graph every format
    below renders."""
    pages, keys = load_pages(root)
    seen = set()
    edges = []

    def add(src, dst, relation):
        key = (src, dst, relation)
        if src != dst and dst is not None and key not in seen:
            seen.add(key)
            edges.append({"source": src, "target": dst,
                          "relation": relation})

    for rel in sorted(pages):
        rec = pages[rel]
        fields, body = rec["fields"], rec["body"]
        for target, _a, _label, _h, ltype in typed_links(body):
            add(rel, _resolve_link(keys, target), str(ltype))
        links_fm = fields.get("links")
        if isinstance(links_fm, dict):
            for relation, targets in links_fm.items():
                for t in as_list(targets):
                    add(rel, _resolve_link(keys, str(t)),
                        str(relation))
        for field, relation in FORWARD_FIELDS.items():
            for t in as_list(fields.get(field)):
                add(rel, _resolve_link(keys, str(t)), relation)
        for field, relation in INVERSE_FIELDS.items():
            for t in as_list(fields.get(field)):
                add(rel, _resolve_link(keys, str(t)), relation)
    edges.sort(key=lambda e: (e["source"], e["target"], e["relation"]))
    return pages, keys, edges


def is_tombstoned(rec) -> bool:
    return bool(rec["tombstoned"])


# --------------------------------------------------------------- jsonld

def node_jsonld(rec, out_edges):
    fields = rec["fields"]
    node = {
        "@id": rec["id"],
        "@type": str(fields.get("type") or "Page"),
        "title": rec["title"],
        "type": str(fields.get("type") or "") or None,
        "tags": [str(t) for t in as_list(fields.get("tags"))],
        "stage": (str(fields["stage"]) if fields.get("stage")
                  is not None else None),
        "status": (str(fields["status"]) if fields.get("status")
                   is not None else None),
        "tombstoned": is_tombstoned(rec),
    }
    if is_tombstoned(rec):
        # The withdrawn state, visible: date, reason and
        # replacement ride on the node whenever the page
        # records them.
        if fields.get("tombstoned") is not None:
            node["tombstone_date"] = str(fields["tombstoned"])
        if fields.get("tombstone_reason") is not None:
            node["tombstone_reason"] = str(fields["tombstone_reason"])
        if fields.get("replaced_by") is not None:
            node["replaced_by"] = str(fields["replaced_by"])
    sources = [str(s) for s in as_list(fields.get("sources"))]
    if sources:
        node["sources"] = sources
    by_relation = {}
    for e in out_edges:
        by_relation.setdefault(e["relation"], []).append(e["target"])
    for relation in sorted(by_relation):
        node[relation] = [{"@id": t}
                          for t in sorted(by_relation[relation])]
    return node


def build_jsonld(root: Path) -> dict:
    pages, _keys, edges = build_graph(root)
    out_by_src = {}
    for e in edges:
        out_by_src.setdefault(e["source"], []).append(e)
    context = {term: {"@type": "@id"} for term in RELATION_TERMS}
    context.update({
        "title": "http://purl.org/dc/terms/title",
        "tombstoned": "http://www.w3.org/2001/XMLSchema#boolean",
    })
    return {
        "@context": context,
        "@graph": [node_jsonld(pages[rel], out_by_src.get(rel, []))
                   for rel in sorted(pages)],
    }


def render_jsonld(root: Path) -> str:
    return json.dumps(build_jsonld(root), indent=2,
                      ensure_ascii=False) + "\n"


# -------------------------------------------------------------- graphml

def _q(tag):
    return "{%s}%s" % (GRAPHML_NS, tag)


_NODE_KEYS = (
    ("title", "string"), ("type", "string"), ("status", "string"),
    ("stage", "string"), ("tags", "string"),
    ("tombstoned", "boolean"),
)


def build_graphml(root: Path) -> ET.ElementTree:
    pages, _keys, edges = build_graph(root)
    ET.register_namespace("", GRAPHML_NS)
    top = ET.Element(_q("graphml"))
    for key_id, attr_type in _NODE_KEYS:
        ET.SubElement(top, _q("key"), {
            "id": key_id, "for": "node", "attr.name": key_id,
            "attr.type": attr_type})
    ET.SubElement(top, _q("key"), {
        "id": "relation", "for": "edge", "attr.name": "relation",
        "attr.type": "string"})
    graph = ET.SubElement(top, _q("graph"), {
        "id": "llm-wiki", "edgedefault": "directed"})
    for rel in sorted(pages):
        rec = pages[rel]
        fields = rec["fields"]
        node = ET.SubElement(graph, _q("node"), {"id": rel})
        values = {
            "title": rec["title"],
            "type": str(fields.get("type") or ""),
            "status": str(fields.get("status") or ""),
            "stage": str(fields.get("stage") or ""),
            "tags": ";".join(str(t)
                             for t in as_list(fields.get("tags"))),
            "tombstoned": "true" if is_tombstoned(rec) else "false",
        }
        for key_id, _t in _NODE_KEYS:
            d = ET.SubElement(node, _q("data"), {"key": key_id})
            d.text = values[key_id]
    for i, e in enumerate(edges):
        edge = ET.SubElement(graph, _q("edge"), {
            "id": "e%d" % i, "source": e["source"],
            "target": e["target"]})
        d = ET.SubElement(edge, _q("data"), {"key": "relation"})
        d.text = e["relation"]
    return ET.ElementTree(top)


def render_graphml(root: Path) -> str:
    tree = build_graphml(root)
    ET.indent(tree, space="  ")
    return ET.tostring(tree.getroot(), encoding="unicode",
                       xml_declaration=True) + "\n"


# ----------------------------------------------------------------- marp

EXCERPT_LIMIT = 800


def excerpt(body: str) -> str:
    """A faithful short excerpt: the body's own opening blocks,
    verbatim, with heading lines dropped (the slide supplies
    its own heading). Blocks accumulate until the limit;
    a single over-long block is cut at a word boundary and
    marked with an ellipsis — the only character added."""
    blocks = []
    total = 0
    for block in re.split(r"\n\s*\n", body.strip()):
        text = block.strip("\n")
        if not text.strip():
            continue
        lines = [ln for ln in text.splitlines()
                 if not ln.lstrip().startswith("#")]
        block = "\n".join(lines).strip("\n")
        if not block.strip():
            continue
        if total + len(block) > EXCERPT_LIMIT and blocks:
            break
        if len(block) > EXCERPT_LIMIT:
            cut = block[:EXCERPT_LIMIT].rsplit(" ", 1)[0]
            blocks.append(cut + "…")
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(blocks)


def page_citations(rec) -> list:
    """The page's source citations: its frontmatter `sources:`
    (the page-level cites record) plus any distinct paths its
    inline ^[cite: ...] markers name, in first-seen order."""
    out = []
    for s in as_list(rec["fields"].get("sources")):
        s = str(s)
        if s not in out:
            out.append(s)
    for m in CITE_MARKER_RE.finditer(rec["body"]):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def render_marp(root: Path, page_ids, link_refs=False) -> str:
    pages, keys, _edges = build_graph(root)
    recs = []
    for pid in page_ids:
        rel = resolve_page(keys, pid)
        if rel is None:
            raise LookupError(pid)
        recs.append(pages[rel])
    if len(recs) == 1:
        deck_title = recs[0]["title"]
    else:
        deck_title = "LLM Wiki — selected pages"
    slides = []
    title_lines = ["# " + deck_title, ""]
    if len(recs) > 1:
        title_lines += ["- " + r["title"] for r in recs]
    slides.append("\n".join(title_lines).rstrip())
    for rec in recs:
        lines = ["## " + rec["title"], ""]
        if is_tombstoned(rec):
            lines += ["> [!warning] Tombstone — this page is "
                      "tombstoned (status: tombstoned).", ""]
        text = excerpt(rec["body"])
        if text:
            lines += [text, ""]
        cites = page_citations(rec)
        lines.append("### Sources")
        lines.append("")
        if cites:
            lines += ["- `%s`" % c for c in cites]
        else:
            lines.append("- None listed on the page.")
        slides.append("\n".join(lines).rstrip())
    frontmatter = "---\nmarp: true\ntitle: %s\n---" % json.dumps(
        deck_title, ensure_ascii=False)
    deck = frontmatter + "\n\n" + "\n\n---\n\n".join(slides) + "\n"
    if link_refs:
        # Foam link-reference option (Marathon R9 lane BB,
        # default OFF): wikilinks become standard Markdown
        # link references so the deck stays navigable without
        # wikilink tooling. Conversion: scripts/wiki_link_refs.
        refs = _load_module("wiki_link_refs",
                            SCRIPTS / "wiki_link_refs.py")
        deck, _defs = refs.convert(deck)
    return deck


# ------------------------------------------------------------------ CLI

def _write_out(text, out_path):
    if out_path is None:
        sys.stdout.write(text)
    else:
        dest = Path(out_path)
        if dest.parent and not dest.parent.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Standard exports of the compiled wiki layer "
                    "(JSON-LD / GraphML / Marp; see module "
                    "docstring).")
    parser.add_argument("--root", default=None,
                        help="repo root (default: this tool's repo); "
                             "may also be given after the subcommand")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, helptext in (
            ("jsonld", "the corpus as JSON-LD"),
            ("graphml", "the corpus graph as GraphML XML")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--out", default=None,
                       help="output file (default: stdout)")
        p.add_argument("--root", dest="root_sub", default=None)

    p_marp = sub.add_parser(
        "marp", help="a Marp slide deck for one or more pages")
    group = p_marp.add_mutually_exclusive_group(required=True)
    group.add_argument("--page", default=None, help="one page id")
    group.add_argument("--pages", default=None,
                       help="comma-separated page ids")
    p_marp.add_argument("--out", default=None,
                        help="output file (default: stdout)")
    p_marp.add_argument("--link-refs", action="store_true",
                        help="render wikilinks as Markdown link "
                             "references (Foam option, default off)")
    p_marp.add_argument("--root", dest="root_sub", default=None)

    args = parser.parse_args(argv)
    # --root is accepted in either position; the subcommand's
    # own wins when both are given. Distinct dests, because an
    # argparse subparser's default would otherwise overwrite
    # the top-level value.
    root_value = args.root_sub or args.root
    root = Path(root_value) if root_value else ROOT

    if args.command == "jsonld":
        _write_out(render_jsonld(root), args.out)
        return 0
    if args.command == "graphml":
        _write_out(render_graphml(root), args.out)
        return 0
    if args.command == "marp":
        ids = [args.page] if args.page else \
            [s for s in args.pages.split(",") if s.strip()]
        try:
            text = render_marp(root, ids,
                               link_refs=args.link_refs)
        except LookupError as exc:
            print("wiki_export: no such page: %s" % exc,
                  file=sys.stderr)
            return 1
        _write_out(text, args.out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
