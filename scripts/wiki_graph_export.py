#!/usr/bin/env python3
"""wiki_graph_export.py — the standalone interactive graph export.

15-gap item 5 (owner-approved under the 2026-10-20 build
delegation): the Lens already has a Graph mode, but it lives
inside the portal build — a reader cannot take it away. This
tool emits ONE self-contained HTML file (default
evaluation/graph.html) that a reader can open offline in any
browser: no server, no build step, no external assets, no CDN.
All CSS and all JavaScript are inline in the file; the graph
data travels as an embedded JSON block.

The graph is the traversal door's graph, not a second
invention: page and edge extraction is delegated to
scripts/wiki_traverse.py (page_graph), which itself walks the
Lens's typed edges (tools/lens/lenslib.py SECTION_TYPE_RULES),
frontmatter `links:` declarations, the relation-vocabulary
fields, and `sources:` citations. This export keeps the
page-to-page edges (wikilink + typed kinds); `sources:`
citation edges point at raw/ files, which are not pages, so
they are not nodes and their edges are not drawn — the census
difference between this file's edge count and the door's is
exactly the citation count.

Each node carries: id (repo-relative path), title, type,
stage and status where the frontmatter provides them, the
out/in degree over the emitted edges, and two standing marks:

  * tombstoned — frontmatter `status: tombstoned` (the
    tombstone convention, AGENTS.md item 18): the page keeps
    its path and its node, drawn with a dashed ring and a
    cross, never dropped from the graph;
  * severed — the page carries a PAGE-level entry in
    evaluation/retrieval-severance.json (item 20): its
    retrieval cues are cut outright, so the node is drawn
    with a red ring. A page that merely CARRIES a severed
    claim (a decision-form or treatment entry naming it) is
    not a severed page; it is flagged separately as
    has_severed_claim and named as such in the details pane.

Interactivity (hand-rolled vanilla JS, no libraries): a
deterministic force-directed layout computed in the browser
from a fixed seed (LAYOUT_SEED in the emitted script — same
corpus, same layout, and the export itself is byte-identical
across runs: no timestamp is embedded), pan and zoom, click
a node to highlight its neighbours, a search box that
focuses a node by title, colour by page type (the Lens's
functional palette), and a details pane with the node's
title, type, tags, out/in degree and neighbour list.

Edge provenance (Marathon Round 3, Lane TA5 — Graphify
pattern, idea only, re-implemented): every edge in the export
carries a `provenance` class. EXTRACTED = the edge is
physically present in a page — a wikilink in the body, a
frontmatter `links:` / relation-vocabulary declaration, or a
`sources:` citation. INFERRED = the edge was derived by a
tool from other facts, not written anywhere: this export
derives exactly one inferred kind, `co-cited` — two pages
whose frontmatter `sources:` cite the same raw source.
Inferred edges travel in their own `inferred_edges` list
(with the shared sources as `evidence`), never in the main
`edges` census: degrees, orphans and communities are
computed over EXTRACTED edges only, so no derived edge can
silently inflate the page graph's own counts. The HTML
renders the distinction: extracted edges are solid grey,
inferred edges are dashed teal and named in the legend.

Graph analytics (Marathon Round 2, Lane G): the export graph
also carries, computed in pure stdlib Python at build time —

  * communities — deterministic label propagation over the
    undirected page graph (nodes visited in sorted id order,
    labels updated in that fixed order, ties broken by the
    smallest label; no randomness, so the partition is
    byte-identical across runs on the same corpus). Each
    node records its community id; the top-level
    "communities" list gives each community's size, sorted
    member ids and top pages (by degree);
  * god nodes — the top 10 pages by total degree (ties:
    higher in-degree, then higher out-degree, then id),
    with in/out degree shown separately;

and the HTML renders a communities panel, a god-nodes
panel, and client-side filters by page type and by tag
(a filtered-out node and its edges are not drawn; the
underlying data is untouched).

Usage:
    python3 scripts/wiki_graph_export.py [--root DIR]
                                         [--out FILE]
                                         [--csr-out FILE]

--csr-out additionally writes the graph's CSR sparse-matrix
form (row 10c; see build_csr).

Stdlib only (this module); graph extraction is delegated to
wiki_traverse as described above.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEVERANCE_REL = "evaluation/retrieval-severance.json"
DEFAULT_OUT_REL = "evaluation/graph.html"


# ---------------------------------------------------------------------------
# Graph extraction (delegated to the traversal door)
# ---------------------------------------------------------------------------

def _load_traverse(root: Path):
    path = Path(root) / "scripts" / "wiki_traverse.py"
    if not path.is_file():
        raise SystemExit(
            f"wiki_graph_export: no traversal door at {path} — "
            "the graph is the door's graph and is not reinvented "
            "here")
    spec = importlib.util.spec_from_file_location(
        "wiki_traverse_for_graph", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_severance(root: Path):
    """(severed_pages, claim_pages) from the severance register.

    severed_pages: pages with a page-level entry (kind "page")
    — severed outright. claim_pages: pages named by any other
    entry — they carry a severed claim but are not themselves
    severed. An absent or unreadable register means severance
    is simply off (the wiki_severance.load_severance rule) and
    both sets are empty."""
    path = Path(root) / SEVERANCE_REL
    severed, claims = set(), set()
    if not path.is_file():
        return severed, claims
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return severed, claims
    if not isinstance(data, dict) \
            or data.get("kind") != "retrieval-severance":
        return severed, claims
    for entry in data.get("entries") or []:
        page = entry.get("page")
        if not page:
            continue
        if entry.get("kind") == "page":
            severed.add(page)
        else:
            claims.add(page)
    return severed, claims


def _scalar(value):
    """A frontmatter value as a display string, or None."""
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    text = str(value).strip().strip('"')
    return text or None


def _tags(value):
    """Frontmatter `tags` as a sorted list of strings.

    Mirrors wiki_validate.as_list's shapes: a list stays a
    list, a flow string "[a, b]" splits on commas, a bare
    scalar is a single tag. Sorting keeps the export
    deterministic whatever order the page declared."""
    if value is None:
        return []
    if isinstance(value, list):
        raw = [str(v) for v in value]
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            raw = text[1:-1].split(",")
        elif text:
            raw = [text]
        else:
            raw = []
    else:
        raw = [str(value)]
    return sorted({t.strip().strip('"').strip("'")
                   for t in raw if t.strip()})


# ---------------------------------------------------------------------------
# Graph analytics: god nodes + deterministic communities
# ---------------------------------------------------------------------------

def compute_god_nodes(nodes, limit=10):
    """The `limit` highest-degree nodes: [{id, title, type,
    degree, out_degree, in_degree}] sorted by total degree
    desc, then in-degree desc, then out-degree desc, then
    id asc — a total order, so the list is deterministic."""
    ranked = sorted(
        nodes,
        key=lambda n: (-(n["out_degree"] + n["in_degree"]),
                       -n["in_degree"], -n["out_degree"], n["id"]))
    return [{
        "id": n["id"], "title": n["title"], "type": n["type"],
        "degree": n["out_degree"] + n["in_degree"],
        "out_degree": n["out_degree"], "in_degree": n["in_degree"],
    } for n in ranked[:limit]]


def compute_communities(nodes, edges):
    """Deterministic label propagation (pure stdlib).

    Undirected view of the emitted edges. Every node starts
    labelled with its own id; passes visit nodes in sorted
    id order and a node adopts the most frequent label among
    its neighbours (ties: the smallest label wins), updating
    in place in that fixed order. Passes repeat until a full
    pass changes nothing (or 100 passes — a hard bound that
    keeps the result finite; the assignment at the bound is
    still fully determined by the fixed order). An isolated
    node keeps its own label and forms a singleton community.

    Returns (assignment, communities): assignment maps node
    id -> community id ("C1", "C2", ... assigned by size
    desc, then smallest member id asc); communities is the
    list of {"id", "label", "size", "members", "top_pages"}
    in that same order, where "label" is the propagation
    label (a member page id) and "top_pages" holds up to 5
    {"id", "title", "degree"} entries by degree desc, id asc.
    """
    ids = sorted(n["id"] for n in nodes)
    by_id = {n["id"]: n for n in nodes}
    degree = {n["id"]: n["out_degree"] + n["in_degree"]
              for n in nodes}
    neighbours = {i: set() for i in ids}
    for e in edges:
        neighbours[e["source"]].add(e["target"])
        neighbours[e["target"]].add(e["source"])
    neighbours = {i: sorted(ns) for i, ns in neighbours.items()}

    labels = {i: i for i in ids}
    for _pass in range(100):
        changed = False
        for node_id in ids:
            ns = neighbours[node_id]
            if not ns:
                continue
            counts = {}
            for nb in ns:
                counts[labels[nb]] = counts.get(labels[nb], 0) + 1
            best = min(counts, key=lambda lab: (-counts[lab], lab))
            if best != labels[node_id]:
                labels[node_id] = best
                changed = True
        if not changed:
            break

    groups = {}
    for node_id in ids:
        groups.setdefault(labels[node_id], []).append(node_id)
    ordered = sorted(groups.items(),
                     key=lambda kv: (-len(kv[1]), kv[1][0]))
    assignment = {}
    communities = []
    for idx, (label, members) in enumerate(ordered, start=1):
        cid = f"C{idx}"
        for m in members:
            assignment[m] = cid
        top = sorted(members,
                     key=lambda m: (-degree[m], m))[:5]
        communities.append({
            "id": cid, "label": label, "size": len(members),
            "members": list(members),
            "top_pages": [{"id": m, "title": by_id[m]["title"],
                           "degree": degree[m]} for m in top],
        })
    return assignment, communities


EXTRACTED_KINDS = ("wikilink", "typed", "citation")


def edge_provenance(edge: dict) -> str:
    """The provenance class of one door edge: EXTRACTED when
    the edge is physically in a page (its kind is one the
    traversal door reads out of page text or frontmatter),
    INFERRED for anything a tool derived."""
    return "EXTRACTED" if edge.get("kind") in EXTRACTED_KINDS \
        else "INFERRED"


def compute_inferred_edges(pages: dict) -> list[dict]:
    """INFERRED co-citation edges: unordered page pairs whose
    frontmatter `sources:` cite the same raw source. Each edge
    carries the shared source paths as `evidence`, sorted, so
    a reader can check the derivation. Deterministic: pairs
    and evidence sorted; self-pairs never emitted."""
    by_source: dict[str, list[str]] = {}
    for rel in sorted(pages):
        fields = pages[rel][0] or {}
        for src in _tags(fields.get("sources")):
            by_source.setdefault(src, []).append(rel)
    shared: dict[tuple, list[str]] = {}
    for src, rels in sorted(by_source.items()):
        for i, a in enumerate(rels):
            for b in rels[i + 1:]:
                shared.setdefault((a, b), []).append(src)
    out = []
    for (a, b), srcs in sorted(shared.items()):
        out.append({"source": a, "target": b,
                    "relation": "co-cited", "kind": "inferred",
                    "provenance": "INFERRED",
                    "evidence": sorted(srcs)})
    return out


def build_csr(graph: dict) -> dict:
    """The graph as a sparse adjacency matrix in CSR form
    (Marathon Round 3, lane TB7, row 10c — the FalkorDB
    sparse-matrix graph representation, re-implemented from
    the idea): rows are the graph's nodes in their emitted
    (sorted) order, each row's entries are the node's
    out-neighbours' column indices in ascending order, values
    are all 1 (an unweighted adjacency; parallel edges emit
    parallel entries, so the matrix still counts edges
    exactly). At scale this is the representation a reader can
    stream and multiply without materialising the edge list
    per node. Returns {"format": "csr", "shape": [n, n],
    "node_ids": [...], "indptr": [...], "indices": [...],
    "values": [...]} — fully determined by the graph dict, so
    the export is byte-identical across runs like the HTML.
    """
    ids = [n["id"] for n in graph["nodes"]]
    col = {nid: i for i, nid in enumerate(ids)}
    rows = {nid: [] for nid in ids}
    for e in graph["edges"]:
        rows[e["source"]].append(col[e["target"]])
    indptr = [0]
    indices = []
    for nid in ids:
        indices.extend(sorted(rows[nid]))
        indptr.append(len(indices))
    return {"format": "csr", "shape": [len(ids), len(ids)],
            "node_ids": ids, "indptr": indptr, "indices": indices,
            "values": [1] * len(indices)}


def build_graph(root: Path) -> dict:
    """The export graph: {"nodes": [...], "edges": [...],
    "counts": {...}} — fully sorted, so the artefact derived
    from it is deterministic.

    Nodes: every compiled page (wiki/**/*.md as the door's
    page_index enumerates it), including orphans, tombstones
    and severed pages. Edges: the door's page-to-page edges
    (kinds wikilink and typed); citation edges to raw/ are
    excluded because their targets are not pages."""
    root = Path(root)
    traverse = _load_traverse(root)
    pages, _keys, all_edges = traverse.page_graph(root)
    severed_pages, claim_pages = load_severance(root)
    page_set = set(pages)

    edges = []
    for e in all_edges:
        if e["kind"] == "citation":
            continue
        if e["src"] not in page_set or e["dst"] not in page_set:
            continue
        edges.append({"source": e["src"], "target": e["dst"],
                      "relation": e["relation"], "kind": e["kind"],
                      "provenance": edge_provenance(e)})
    edges.sort(key=lambda e: (e["source"], e["target"],
                              e["relation"], e["kind"]))

    out_deg = {rel: 0 for rel in page_set}
    in_deg = {rel: 0 for rel in page_set}
    for e in edges:
        out_deg[e["source"]] += 1
        in_deg[e["target"]] += 1

    nodes = []
    for rel in sorted(pages):
        fields, _body, _text = pages[rel]
        fields = fields or {}
        status = _scalar(fields.get("status"))
        nodes.append({
            "id": rel,
            "title": _scalar(fields.get("title"))
                     or Path(rel).stem,
            "type": _scalar(fields.get("type")),
            "tags": _tags(fields.get("tags")),
            "stage": _scalar(fields.get("stage")),
            "status": status,
            "tombstoned": bool(status
                               and status.lower() == "tombstoned"),
            "severed": rel in severed_pages,
            "has_severed_claim": rel in claim_pages,
            "out_degree": out_deg[rel],
            "in_degree": in_deg[rel],
        })
    assignment, communities = compute_communities(nodes, edges)
    for n in nodes:
        n["community"] = assignment[n["id"]]
    god_nodes = compute_god_nodes(nodes)
    inferred_edges = compute_inferred_edges(pages)
    counts = {
        "pages": len(nodes),
        "edges": len(edges),
        "extracted_edges": len(edges),
        "inferred_edges": len(inferred_edges),
        "tombstoned": sum(1 for n in nodes if n["tombstoned"]),
        "severed": sum(1 for n in nodes if n["severed"]),
        "orphans": sum(1 for n in nodes
                       if n["out_degree"] == 0
                       and n["in_degree"] == 0),
        "communities": len(communities),
    }
    return {"nodes": nodes, "edges": edges,
            "inferred_edges": inferred_edges, "counts": counts,
            "communities": communities, "god_nodes": god_nodes}


# ---------------------------------------------------------------------------
# The standalone HTML artefact
# ---------------------------------------------------------------------------

def graph_data_json(graph: dict) -> str:
    """The embedded data block: sorted keys, and the escapes
    that keep page text from closing the script element."""
    text = json.dumps(graph, sort_keys=True, ensure_ascii=False)
    return (text.replace("</", "<\\/")
                .replace("\u2028", "\\u2028")
                .replace("\u2029", "\\u2029"))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Wiki — Link Graph</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Segoe UI", Roboto,
         Helvetica, Arial, sans-serif; background: #faf9f6;
         color: #1c1a17; }
  header { padding: 10px 16px; border-bottom: 1px solid #ddd6c9;
           background: #fff; }
  header h1 { font-size: 17px; margin: 0 0 4px; }
  #stats { margin: 0 0 8px; font-size: 13px; color: #5c564a; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px;
              align-items: center; }
  #search { flex: 0 1 320px; padding: 6px 9px; font-size: 14px;
            border: 1px solid #b9b2a4; border-radius: 6px; }
  button { padding: 6px 12px; font-size: 13px; cursor: pointer;
           border: 1px solid #b9b2a4; border-radius: 6px;
           background: #f2eee6; }
  button:hover { background: #e9e2d2; }
  #search-status { font-size: 13px; color: #8a2f23; min-height: 1em; }
  #legend { display: flex; flex-wrap: wrap; gap: 6px 14px;
            margin-top: 8px; font-size: 12.5px; color: #44403a; }
  .swatch { display: inline-block; width: 11px; height: 11px;
            border-radius: 50%; margin-right: 5px;
            border: 1px solid rgba(0,0,0,0.25);
            vertical-align: -1px; }
  main { display: flex; align-items: stretch; }
  #canvas-wrap { flex: 1 1 auto; min-width: 0; }
  canvas { display: block; width: 100%; height: calc(100vh - 132px);
           cursor: grab; touch-action: none; }
  canvas:active { cursor: grabbing; }
  #details { flex: 0 0 300px; border-left: 1px solid #ddd6c9;
             background: #fff; padding: 12px 14px;
             overflow-y: auto; height: calc(100vh - 132px);
             font-size: 13.5px; }
  #details h2 { font-size: 15px; margin: 0 0 6px; }
  #details .path { color: #6b6455; font-size: 12px;
                   word-break: break-all; }
  #details dl { display: grid; grid-template-columns: auto 1fr;
                gap: 2px 10px; margin: 10px 0; }
  #details dt { color: #6b6455; }
  #details dd { margin: 0; }
  .badge { display: inline-block; padding: 1px 7px; border-radius: 8px;
           font-size: 11.5px; font-weight: 600; margin: 2px 4px 2px 0; }
  .badge-tombstoned { background: #e3ded2; color: #4c463c;
                      border: 1px dashed #6b6455; }
  .badge-severed { background: #f6dcd8; color: #8a2f23;
                   border: 1px solid #c0392b; }
  .badge-claim { background: #fdf0d5; color: #7a5410;
                 border: 1px solid #d9a441; }
  #details ul { list-style: none; padding: 0; margin: 6px 0; }
  #details li { margin: 0 0 4px; }
  #details li button { width: 100%; text-align: left;
                       background: #faf9f6; }
  .hint { color: #6b6455; font-size: 12.5px; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px;
             align-items: center; margin-top: 8px; font-size: 13px; }
  .filters select { padding: 5px 7px; font-size: 13px;
                    border: 1px solid #b9b2a4; border-radius: 6px;
                    background: #fff; }
  #filter-status { font-size: 12.5px; color: #5c564a; }
  #panels { display: flex; flex-wrap: wrap; gap: 0;
            border-bottom: 1px solid #ddd6c9; background: #fff; }
  .panel { flex: 1 1 340px; padding: 8px 16px 10px;
           max-height: 190px; overflow-y: auto; }
  .panel + .panel { border-left: 1px solid #ddd6c9; }
  .panel h2 { font-size: 13.5px; margin: 2px 0 6px; }
  .panel ul { list-style: none; padding: 0; margin: 0;
              font-size: 12.5px; }
  .panel li { margin: 0 0 4px; }
  .panel li button { padding: 2px 7px; font-size: 12px; }
  .panel .meta { color: #6b6455; }
</style>
</head>
<body>
<header>
  <h1>LLM Wiki — Link Graph</h1>
  <p id="stats"></p>
  <div class="controls">
    <input id="search" type="search" list="title-list"
           placeholder="Search by title…" aria-label="Search by title">
    <datalist id="title-list"></datalist>
    <button id="search-btn" type="button">Find</button>
    <button id="reset-btn" type="button">Reset view</button>
    <span id="search-status" role="status"></span>
  </div>
  <div id="legend" aria-label="Legend"></div>
  <div class="filters" aria-label="Graph filters">
    <label>Filter by type
      <select id="filter-type" aria-label="Filter by page type">
        <option value="">All types</option>
      </select>
    </label>
    <label>Filter by tag
      <select id="filter-tag" aria-label="Filter by tag">
        <option value="">All tags</option>
      </select>
    </label>
    <button id="filter-clear" type="button">Clear filters</button>
    <span id="filter-status" role="status"></span>
  </div>
</header>
<section id="panels" aria-label="Graph analytics">
  <div class="panel" id="communities-panel">
    <h2>Communities</h2>
    <ul id="communities-list"></ul>
  </div>
  <div class="panel" id="god-nodes-panel">
    <h2>God nodes (top 10 by degree)</h2>
    <ul id="god-nodes-list"></ul>
  </div>
</section>
<main>
  <div id="canvas-wrap"><canvas id="graph"></canvas></div>
  <aside id="details" aria-label="Node details">
    <h2>No node selected</h2>
    <p class="hint">Click a node to see its details and highlight
    its neighbours. Drag to pan, scroll to zoom, drag a node to
    move it. Tombstoned pages carry a dashed ring and a cross;
    severed pages a red ring.</p>
  </aside>
</main>
<script id="graph-data" type="application/json">__GRAPH_DATA_JSON__</script>
<script>
"use strict";
var DATA = JSON.parse(document.getElementById("graph-data").textContent);
var LAYOUT_SEED = 20261020;
var TYPE_COLORS = {
  "source": "#F2994A",
  "entity": "#5B8DEF",
  "concept": "#A06CD5",
  "synthesis": "#5FA88F",
  "query": "#95A5A6"
};
var FALLBACK_COLOR = "#95A5A6";
function colorForType(type) {
  if (type && Object.prototype.hasOwnProperty.call(TYPE_COLORS, type)) {
    return TYPE_COLORS[type];
  }
  return FALLBACK_COLOR;
}
function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
var nodes = DATA.nodes;
var edges = DATA.edges;
var inferredEdges = DATA.inferred_edges || [];
var communities = DATA.communities || [];
var godNodes = DATA.god_nodes || [];
var byId = {};
nodes.forEach(function (n) { byId[n.id] = n; });
var activeFilter = { type: "", tag: "" };
function nodeMatchesFilter(node) {
  if (activeFilter.type && node.type !== activeFilter.type) { return false; }
  if (activeFilter.tag &&
      (node.tags || []).indexOf(activeFilter.tag) === -1) { return false; }
  return true;
}
function isFilteredOut(id) { return !nodeMatchesFilter(byId[id]); }
function visibleCount() {
  return nodes.filter(nodeMatchesFilter).length;
}
function applyFilters() {
  activeFilter.type = document.getElementById("filter-type").value;
  activeFilter.tag = document.getElementById("filter-tag").value;
  var status = document.getElementById("filter-status");
  if (!activeFilter.type && !activeFilter.tag) {
    status.textContent = "";
  } else {
    status.textContent = visibleCount() + " of " + nodes.length +
      " pages shown.";
  }
  if (selectedId && isFilteredOut(selectedId)) { selectNode(null); }
  draw();
}
var outAdj = {}, inAdj = {}, allAdj = {};
nodes.forEach(function (n) {
  outAdj[n.id] = []; inAdj[n.id] = []; allAdj[n.id] = {};
});
edges.forEach(function (e) {
  outAdj[e.source].push(e);
  inAdj[e.target].push(e);
  allAdj[e.source][e.target] = true;
  allAdj[e.target][e.source] = true;
});
function neighboursOf(id) {
  return Object.keys(allAdj[id]).sort().map(function (k) { return byId[k]; });
}
function computeLayout() {
  var rand = mulberry32(LAYOUT_SEED);
  var n = nodes.length;
  nodes.forEach(function (node) {
    node.x = (rand() * 2 - 1) * 420;
    node.y = (rand() * 2 - 1) * 420;
    node._dx = 0; node._dy = 0;
  });
  if (n === 0) { return; }
  var area = 920 * 920;
  var k = Math.sqrt(area / n);
  var iterations = 400;
  for (var it = 0; it < iterations; it++) {
    var temp = 70 * (1 - it / iterations) + 2;
    nodes.forEach(function (node) { node._dx = 0; node._dy = 0; });
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        var a = nodes[i], b = nodes[j];
        var dx = a.x - b.x, dy = a.y - b.y;
        var d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = (i - j) * 0.1 + 0.05; dy = 0.07; d2 = dx * dx + dy * dy; }
        var d = Math.sqrt(d2);
        var f = (k * k) / d;
        var ux = dx / d, uy = dy / d;
        a._dx += ux * f; a._dy += uy * f;
        b._dx -= ux * f; b._dy -= uy * f;
      }
    }
    edges.forEach(function (e) {
      var a = byId[e.source], b = byId[e.target];
      var dx = a.x - b.x, dy = a.y - b.y;
      var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      var f = (d * d) / k;
      var ux = dx / d, uy = dy / d;
      a._dx -= ux * f; a._dy -= uy * f;
      b._dx += ux * f; b._dy += uy * f;
    });
    nodes.forEach(function (node) {
      var dl = Math.sqrt(node._dx * node._dx + node._dy * node._dy) || 0.01;
      var step = Math.min(dl, temp);
      node.x += (node._dx / dl) * step;
      node.y += (node._dy / dl) * step;
    });
  }
  var mx = 0, my = 0;
  nodes.forEach(function (node) { mx += node.x; my += node.y; });
  mx /= n; my /= n;
  nodes.forEach(function (node) { node.x -= mx; node.y -= my; });
}
computeLayout();
var canvas = document.getElementById("graph");
var ctx = canvas.getContext("2d");
var view = { scale: 1, tx: 0, ty: 0 };
var selectedId = null;
var hoverId = null;
var highlighted = null;
function nodeRadius(node) {
  return 6 + Math.min(11, (node.out_degree + node.in_degree) * 0.65);
}
function resize() {
  var r = canvas.getBoundingClientRect();
  var dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(r.width * dpr));
  canvas.height = Math.max(1, Math.round(r.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}
function canvasSize() {
  var r = canvas.getBoundingClientRect();
  return { w: r.width, h: r.height };
}
function fitView() {
  var s = canvasSize();
  if (!nodes.length) { view = { scale: 1, tx: s.w / 2, ty: s.h / 2 }; return; }
  var minX = 1e18, maxX = -1e18, minY = 1e18, maxY = -1e18;
  nodes.forEach(function (node) {
    minX = Math.min(minX, node.x); maxX = Math.max(maxX, node.x);
    minY = Math.min(minY, node.y); maxY = Math.max(maxY, node.y);
  });
  var w = Math.max(60, maxX - minX), h = Math.max(60, maxY - minY);
  var scale = Math.min(s.w / (w + 90), s.h / (h + 90), 1.4);
  view.scale = scale;
  view.tx = s.w / 2 - ((minX + maxX) / 2) * scale;
  view.ty = s.h / 2 - ((minY + maxY) / 2) * scale;
}
function toScreen(node) {
  return { x: node.x * view.scale + view.tx, y: node.y * view.scale + view.ty };
}
function toWorld(px, py) {
  return { x: (px - view.tx) / view.scale, y: (py - view.ty) / view.scale };
}
function isDimmed(id) {
  return highlighted !== null && !highlighted[id];
}
function draw() {
  var s = canvasSize();
  ctx.clearRect(0, 0, s.w, s.h);
  edges.forEach(function (e) {
    if (isFilteredOut(e.source) || isFilteredOut(e.target)) { return; }
    var a = toScreen(byId[e.source]), b = toScreen(byId[e.target]);
    var hot = selectedId !== null &&
      (e.source === selectedId || e.target === selectedId);
    ctx.globalAlpha = highlighted === null ? 0.55 : (hot ? 0.95 : 0.07);
    ctx.strokeStyle = hot ? "#33302a" : "#b9b2a4";
    ctx.lineWidth = hot ? 1.6 : 1;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  });
  ctx.globalAlpha = 1;
  inferredEdges.forEach(function (e) {
    if (isFilteredOut(e.source) || isFilteredOut(e.target)) { return; }
    var a = toScreen(byId[e.source]), b = toScreen(byId[e.target]);
    ctx.globalAlpha = 0.75;
    ctx.strokeStyle = "#2a7f7f";
    ctx.lineWidth = 1.2;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    ctx.setLineDash([]);
  });
  ctx.globalAlpha = 1;
  nodes.forEach(function (node) {
    if (isFilteredOut(node.id)) { return; }
    var p = toScreen(node);
    var r = nodeRadius(node);
    ctx.globalAlpha = isDimmed(node.id) ? 0.18 : 1;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = colorForType(node.type);
    ctx.fill();
    ctx.lineWidth = node.id === selectedId ? 2.6 : 1.2;
    ctx.strokeStyle = node.id === selectedId ? "#1c1a17" : "#5c564a";
    ctx.stroke();
    if (node.severed) {
      ctx.beginPath(); ctx.arc(p.x, p.y, r + 4.5, 0, Math.PI * 2);
      ctx.lineWidth = 2.4; ctx.strokeStyle = "#c0392b"; ctx.stroke();
    }
    if (node.tombstoned) {
      ctx.beginPath(); ctx.arc(p.x, p.y, r + (node.severed ? 9 : 4.5), 0, Math.PI * 2);
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.6; ctx.strokeStyle = "#6b6455"; ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(p.x - r * 0.7, p.y - r * 0.7);
      ctx.lineTo(p.x + r * 0.7, p.y + r * 0.7);
      ctx.moveTo(p.x + r * 0.7, p.y - r * 0.7);
      ctx.lineTo(p.x - r * 0.7, p.y + r * 0.7);
      ctx.lineWidth = 1.4; ctx.strokeStyle = "#4c463c"; ctx.stroke();
    }
    var showLabel = view.scale >= 0.5 || node.id === selectedId ||
      node.id === hoverId || (highlighted !== null && !!highlighted[node.id]);
    if (showLabel) {
      var label = node.title.length > 30 ? node.title.slice(0, 29) + "…" : node.title;
      ctx.font = "11px sans-serif";
      ctx.textAlign = "center";
      ctx.fillStyle = "#1c1a17";
      ctx.fillText(label, p.x, p.y + r + 13);
    }
    ctx.globalAlpha = 1;
  });
}
function highlightNeighbours(id) {
  highlighted = {};
  highlighted[id] = true;
  neighboursOf(id).forEach(function (nb) { highlighted[nb.id] = true; });
}
function clearHighlight() { highlighted = null; }
function selectNode(id) {
  selectedId = id;
  if (id) { highlightNeighbours(id); showDetails(byId[id]); }
  else { clearHighlight(); showNoSelection(); }
  draw();
}
function focusNode(id) {
  var node = byId[id];
  if (!node) { return; }
  var s = canvasSize();
  if (view.scale < 0.85) { view.scale = 1; }
  view.tx = s.w / 2 - node.x * view.scale;
  view.ty = s.h / 2 - node.y * view.scale;
  selectNode(id);
}
function searchByTitle(query) {
  var status = document.getElementById("search-status");
  var q = (query || "").trim().toLowerCase();
  if (!q) { status.textContent = ""; return; }
  var exact = null, partial = [];
  nodes.forEach(function (node) {
    var t = node.title.toLowerCase();
    if (t === q) { exact = node; }
    else if (t.indexOf(q) !== -1) { partial.push(node); }
  });
  partial.sort(function (a, b) { return a.title < b.title ? -1 : 1; });
  var hit = exact || partial[0];
  if (!hit) {
    status.textContent = "No page title matches “" + query.trim() + "”.";
    return;
  }
  status.textContent = "";
  focusNode(hit.id);
}
function el(tag, text) {
  var n = document.createElement(tag);
  if (text !== undefined) { n.textContent = text; }
  return n;
}
function showNoSelection() {
  var pane = document.getElementById("details");
  pane.innerHTML = "";
  pane.appendChild(el("h2", "No node selected"));
  var p = el("p", "Click a node to see its details and highlight its neighbours.");
  p.className = "hint";
  pane.appendChild(p);
}
function showDetails(node) {
  var pane = document.getElementById("details");
  pane.innerHTML = "";
  pane.appendChild(el("h2", node.title));
  var path = el("p", node.id); path.className = "path"; pane.appendChild(path);
  if (node.tombstoned) {
    var b1 = el("span", "TOMBSTONED"); b1.className = "badge badge-tombstoned";
    pane.appendChild(b1);
  }
  if (node.severed) {
    var b2 = el("span", "SEVERED"); b2.className = "badge badge-severed";
    pane.appendChild(b2);
  }
  if (node.has_severed_claim) {
    var b3 = el("span", "carries a severed claim");
    b3.className = "badge badge-claim"; pane.appendChild(b3);
  }
  var dl = el("dl");
  function row(k, v) {
    dl.appendChild(el("dt", k));
    dl.appendChild(el("dd", v === null || v === undefined || v === "" ? "—" : String(v)));
  }
  row("Type", node.type);
  row("Tags", (node.tags || []).join(", "));
  row("Community", node.community);
  row("Stage", node.stage);
  row("Status", node.status);
  row("Out-degree", node.out_degree);
  row("In-degree", node.in_degree);
  pane.appendChild(dl);
  pane.appendChild(el("h3", "Neighbours (" + neighboursOf(node.id).length + ")"));
  var ul = el("ul");
  var seen = {};
  function addItem(otherId, arrow, relation) {
    var key = otherId + "|" + arrow + "|" + relation;
    if (seen[key]) { return; } seen[key] = true;
    var li = el("li");
    var btn = el("button", arrow + " " + byId[otherId].title + " (" + relation + ")");
    btn.type = "button";
    btn.addEventListener("click", function () { focusNode(otherId); });
    li.appendChild(btn);
    ul.appendChild(li);
  }
  outAdj[node.id].forEach(function (e) { addItem(e.target, "→", e.relation); });
  inAdj[node.id].forEach(function (e) { addItem(e.source, "←", e.relation); });
  if (!ul.children.length) {
    ul.appendChild(el("li", "No neighbours — this page is an orphan in the graph."));
  }
  pane.appendChild(ul);
}
function buildPanels() {
  var clist = document.getElementById("communities-list");
  communities.forEach(function (c) {
    var li = el("li");
    var head = el("strong", c.id + " — " + c.size +
      (c.size === 1 ? " page" : " pages"));
    li.appendChild(head);
    var tops = (c.top_pages || []).map(function (p) { return p.title; });
    if (tops.length) {
      var meta = el("span", " · top: " + tops.join(", "));
      meta.className = "meta";
      li.appendChild(meta);
    }
    clist.appendChild(li);
  });
  if (!communities.length) {
    clist.appendChild(el("li", "No communities — the graph is empty."));
  }
  var glist = document.getElementById("god-nodes-list");
  godNodes.forEach(function (g) {
    var li = el("li");
    var btn = el("button", g.title);
    btn.type = "button";
    btn.addEventListener("click", function () { focusNode(g.id); });
    li.appendChild(btn);
    var meta = el("span", " degree " + g.degree +
      " (in " + g.in_degree + " / out " + g.out_degree + ")");
    meta.className = "meta";
    li.appendChild(meta);
    glist.appendChild(li);
  });
  if (!godNodes.length) {
    glist.appendChild(el("li", "No god nodes — the graph is empty."));
  }
}
function buildFilters() {
  var typeSel = document.getElementById("filter-type");
  var typesSeen = {};
  nodes.forEach(function (node) { if (node.type) { typesSeen[node.type] = true; } });
  Object.keys(typesSeen).sort().forEach(function (t) {
    var o = el("option", t); o.value = t; typeSel.appendChild(o);
  });
  var tagSel = document.getElementById("filter-tag");
  var tagsSeen = {};
  nodes.forEach(function (node) {
    (node.tags || []).forEach(function (t) { tagsSeen[t] = true; });
  });
  Object.keys(tagsSeen).sort().forEach(function (t) {
    var o = el("option", t); o.value = t; tagSel.appendChild(o);
  });
  typeSel.addEventListener("change", applyFilters);
  tagSel.addEventListener("change", applyFilters);
  document.getElementById("filter-clear").addEventListener("click", function () {
    typeSel.value = ""; tagSel.value = ""; applyFilters();
  });
}
function buildChrome() {
  var c = DATA.counts;
  document.getElementById("stats").textContent =
    c.pages + " pages · " + c.edges + " extracted edges · " +
    (c.inferred_edges || 0) + " inferred edges · " +
    c.tombstoned + " tombstoned · " + c.severed + " severed · " +
    c.orphans + " orphans — standalone export, works offline.";
  var dl = document.getElementById("title-list");
  nodes.forEach(function (node) {
    var o = el("option"); o.value = node.title; dl.appendChild(o);
  });
  var legend = document.getElementById("legend");
  var typesSeen = {};
  nodes.forEach(function (node) { if (node.type) { typesSeen[node.type] = true; } });
  Object.keys(typesSeen).sort().forEach(function (t) {
    var span = el("span");
    var sw = el("span"); sw.className = "swatch";
    sw.style.background = colorForType(t);
    span.appendChild(sw);
    span.appendChild(document.createTextNode(t));
    legend.appendChild(span);
  });
  var t0 = el("span", "┄ teal dashed — INFERRED edge (co-cited, derived by the export; solid grey edges are EXTRACTED from a page)");
  legend.appendChild(t0);
  var t1 = el("span", "○ dashed ring + cross — tombstoned");
  var t2 = el("span", "◎ red ring — severed");
  legend.appendChild(t1); legend.appendChild(t2);
  document.getElementById("search-btn").addEventListener("click", function () {
    searchByTitle(document.getElementById("search").value);
  });
  document.getElementById("search").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { searchByTitle(ev.target.value); }
  });
  document.getElementById("reset-btn").addEventListener("click", function () {
    selectNode(null); fitView(); draw();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { selectNode(null); }
  });
}
function hitTest(px, py) {
  var w = toWorld(px, py);
  for (var i = nodes.length - 1; i >= 0; i--) {
    var node = nodes[i];
    if (isFilteredOut(node.id)) { continue; }
    var dx = node.x - w.x, dy = node.y - w.y;
    var r = (nodeRadius(node) + 4) / view.scale;
    if (dx * dx + dy * dy <= r * r) { return node; }
  }
  return null;
}
var drag = null;
function canvasPos(ev) {
  var r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}
canvas.addEventListener("pointerdown", function (ev) {
  var p = canvasPos(ev);
  var hit = hitTest(p.x, p.y);
  drag = { x: p.x, y: p.y, moved: false, node: hit,
           tx: view.tx, ty: view.ty,
           nx: hit ? hit.x : 0, ny: hit ? hit.y : 0 };
  canvas.setPointerCapture(ev.pointerId);
});
canvas.addEventListener("pointermove", function (ev) {
  var p = canvasPos(ev);
  if (!drag) {
    var h = hitTest(p.x, p.y);
    var hid = h ? h.id : null;
    if (hid !== hoverId) { hoverId = hid; draw(); }
    return;
  }
  var dx = p.x - drag.x, dy = p.y - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; }
  if (!drag.moved) { return; }
  if (drag.node) {
    drag.node.x = drag.nx + dx / view.scale;
    drag.node.y = drag.ny + dy / view.scale;
  } else {
    view.tx = drag.tx + dx; view.ty = drag.ty + dy;
  }
  draw();
});
canvas.addEventListener("pointerup", function (ev) {
  if (drag && !drag.moved) {
    if (drag.node) { selectNode(drag.node.id); }
    else { selectNode(null); }
  }
  drag = null;
  draw();
});
canvas.addEventListener("wheel", function (ev) {
  ev.preventDefault();
  var p = canvasPos(ev);
  var before = toWorld(p.x, p.y);
  var factor = Math.exp(-ev.deltaY * 0.0012);
  view.scale = Math.min(4, Math.max(0.08, view.scale * factor));
  view.tx = p.x - before.x * view.scale;
  view.ty = p.y - before.y * view.scale;
  draw();
}, { passive: false });
window.addEventListener("resize", resize);
buildPanels();
buildFilters();
buildChrome();
fitView();
resize();
</script>
</body>
</html>
"""


def render_html(graph: dict) -> str:
    """The standalone file's text for a built graph. Pure and
    deterministic: same graph in, same bytes out."""
    return TEMPLATE.replace("__GRAPH_DATA_JSON__",
                            graph_data_json(graph))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the standalone interactive graph "
                    "HTML export (see module docstring).")
    parser.add_argument("--root", default=None,
                        help="repo root (default: this tool's repo)")
    parser.add_argument("--out", default=None,
                        help="output file (default: "
                             "<root>/evaluation/graph.html)")
    parser.add_argument("--csr-out", default=None,
                        help="also write the CSR sparse-matrix "
                             "export (row 10c) as JSON here")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    out = Path(args.out) if args.out else root / DEFAULT_OUT_REL
    graph = build_graph(root)
    if args.csr_out:
        csr_path = Path(args.csr_out)
        csr_path.parent.mkdir(parents=True, exist_ok=True)
        csr_path.write_text(json.dumps(build_csr(graph), indent=2,
                                       sort_keys=True) + "\n",
                            encoding="utf-8")
        print(f"graph CSR: {len(graph['nodes'])} nodes, "
              f"{len(graph['edges'])} nonzeros -> {csr_path}")
    text = render_html(graph)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    c = graph["counts"]
    print(f"graph export: {c['pages']} pages · {c['edges']} extracted "
          f"edges · {c['inferred_edges']} inferred edges "
          f"({c['tombstoned']} tombstoned, {c['severed']} severed, "
          f"{c['orphans']} orphans, {c['communities']} communities) "
          f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
