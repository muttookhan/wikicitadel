"""Build-time Mermaid rendering for the Lens (Wave-2 item W2).

A fenced ```mermaid block in a page is compiled at Lens build time
to an inline SVG by our own subset parser — the same pattern as the
Argdown compiler (item 63c, stateviews.parse_argdown). Nothing is
vendored and no Mermaid engine is available offline in this
environment (surveyed 2026-10-22: no mmdc binary, empty global
node_modules, no mermaid asset anywhere in the tree), so this module
is an independent implementation of the documented Mermaid syntax
subset below. Mermaid itself is MIT (mermaid.js.org); the syntax and
the adapt-with-credit route are recorded here per house convention.

Renderer interface (what build_lens consumes):

  lift_mermaid(body) -> (body, figures, infos)
      Lift every ```mermaid fence out of a page body, replacing it
      with a LENSMERMAIDFIG<i> placeholder paragraph; `figures` are
      the finished figure HTML strings to substitute back after
      markdown rendering, `infos` the per-block census records.
  parse_mermaid(src) -> model dict (type, nodes, edges, slices,
      unparsed, warnings) — pure, deterministic.
  mermaid_svg(model) -> (svg, warnings); svg is "" when the type is
      outside the supported subset.
  figure_html(src) -> the complete <figure> for one block: the SVG
      plus the source block (kept visible as the source of truth),
      or — for an unsupported type — the named unrendered state with
      the source shown as-is. A diagram is never silently dropped.
  sanitize_svg(svg) -> svg, or "" if the generated markup carries a
      forbidden construct (script, event handlers, external refs).
      Defence in depth: labels are escaped at emission, so a clean
      renderer never trips this; the check exists so a future
      renderer change cannot smuggle markup into the built site.

Supported subset (stated, deliberately bounded):
  * flowchart / graph — directions TD TB LR RL BT; node shapes
    [rect] (rounded) ([stadium]) [[subroutine]] [(cylinder)]
    {diamond} ((circle)) >flag]; edges --> --- -.-> -.- ==> <-->
    --x --o, with -->|label| postfix labels and -- label -->
    inline labels; chains (A --> B --> C) and & fan-out; node-only
    declaration lines; `direction XX` lines; subgraph blocks are
    read (their contents render) but their boundaries are NOT
    drawn — a warning says so on the figure.
  * stateDiagram / stateDiagram-v2 — states, [*] pseudostates,
    transitions with : labels, `state "desc" as id` declarations
    and `id : description` lines; direction lines honoured.
  * pie — optional title, optional showData, "label" : value
    slices; drawn as slices plus a legend carrying value and
    percentage beside every mark.
  Everything else (sequenceDiagram, classDiagram, erDiagram,
  gantt, gitGraph, mindmap, ...) is a NAMED FALLBACK: the figure
  states the type is outside the supported subset and shows the
  source block as-is. classDef / class / style / linkStyle / click
  lines inside a supported diagram are returned in `unparsed`,
  never silently dropped.

Determinism: layout is longest-path ranking with name-ordered
tiebreaks, the palette is a fixed constant list, coordinates are
formatted %.0f / %.1f, and the SVG carries no ids, no defs and no
timestamps (arrowheads are plain polygons), so the same page
compiles to the same bytes on every build.
"""

from __future__ import annotations

import html
import math
import re

SUPPORTED_TYPES = ("flowchart", "state", "pie")

# Fixed dark-theme palette (matches the Argdown compiler's tones).
_INK = "#F2EEE6"
_DIM = "#B9B2A4"
_EDGE = "#8A8272"
_BOX_FILL = "#1F1C17"
_BOX_LINE = "#454034"
_PIE_FILLS = ["#5FA88F", "#D9A441", "#5B8DD9", "#D95D4E", "#9B7ED9",
              "#4FB3B3", "#C97B9A", "#7FA653", "#B08968", "#6E7FDB"]

_TYPE_HEADS = (
    ("flowchart", "flowchart"), ("graph", "flowchart"),
    ("stateDiagram-v2", "state"), ("stateDiagram", "state"),
    ("pie", "pie"),
)

_KNOWN_UNSUPPORTED = {
    "sequenceDiagram", "classDiagram", "classDiagram-v2",
    "erDiagram", "gantt", "userJourney", "journey", "gitGraph",
    "mindmap", "timeline", "quadrantChart", "xychart-beta",
    "sankey-beta", "block-beta", "packet-beta", "architecture",
    "architecture-beta", "kanban", "radar-beta", "treemap-beta",
    "requirementDiagram", "C4Context", "C4Container", "C4Component",
    "C4Dynamic", "C4Deployment", "zenuml", "flowchart-elk",
}

_ID = r"[A-Za-z0-9_][A-Za-z0-9_-]*"
_NODE_RE = re.compile(
    rf"(?P<id>{_ID})"
    r"(?:\(\((?P<circle>.*?)\)\)"
    r"|\(\[(?P<stadium>.*?)\]\)"
    r"|\[\[(?P<subroutine>.*?)\]\]"
    r"|\[\((?P<cylinder>.*?)\)\]"
    r"|\{(?P<diamond>.*?)\}"
    r"|\((?P<rounded>.*?)\)"
    r"|\[(?P<rect>.*?)\]"
    r"|>(?P<flag>.*?)\])?")
# State diagrams reference the [*] pseudostate as a node; it is a
# legal node token there and nowhere else.
_STATE_NODE_RE = re.compile(
    r"(?P<id>\[\*\])"
    r"|(?P<id2>" + _ID + r")"
    r"(?:\(\((?P<circle>.*?)\)\)"
    r"|\(\[(?P<stadium>.*?)\]\)"
    r"|\[\[(?P<subroutine>.*?)\]\]"
    r"|\[\((?P<cylinder>.*?)\)\]"
    r"|\{(?P<diamond>.*?)\}"
    r"|\((?P<rounded>.*?)\)"
    r"|\[(?P<rect>.*?)\]"
    r"|>(?P<flag>.*?)\])?")
_CONN_RE = re.compile(
    r"\s*(?:"
    r"(?P<kind><-->|-\.->|-\.-|==>|-->|---|--x|--o)"
    r"(?:\|(?P<label>[^|]*)\|)?"
    r"|--\s*(?P<ilabel>.+?)\s*(?P<ikind>-->|---)"
    r"|==\s*(?P<tlabel>.+?)\s*==>"
    r"|-\.\s*(?P<dlabel>.+?)\s*\.->"
    r")\s*")
_PIE_SLICE_RE = re.compile(
    r'^\s*(?:"(?P<q>[^"]+)"|(?P<bare>[^:"]+?))\s*:\s*'
    r"(?P<val>[0-9]+(?:\.[0-9]+)?)\s*$")
_STATE_DECL_RE = re.compile(
    rf'^state\s+"(?P<desc>[^"]+)"\s+as\s+(?P<id>{_ID})\s*$')
_STATE_DESC_RE = re.compile(rf"^(?P<id>{_ID})\s*:\s*(?P<desc>.+)$")

FENCE_RE = re.compile(r"(?ms)^```mermaid[ \t]*\n(.*?)^```[ \t]*$")


def diagram_type(src):
    """The model's type key + the raw head word, from the first
    meaningful line (blank lines and %% comments skipped)."""
    for raw in str(src).splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if line == "---":  # frontmatter — keep scanning for a head
            continue
        head = line.split()[0] if line.split() else ""
        for word, key in _TYPE_HEADS:
            if line.startswith(word):
                return key, word
        return "unsupported", head
    return "unsupported", ""


def _clean_label(text):
    text = str(text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text.replace("<br/>", " ").replace("<br>", " ").strip()


def _strip_comment(line):
    return line.split("%%", 1)[0].rstrip()


class _Graph:
    """Node/edge pool shared by the flowchart and state parsers."""

    def __init__(self):
        self.nodes = {}   # id -> {"label": str, "shape": str}
        self.edges = []   # {"from","to","kind","label"}

    def node(self, nid, label=None, shape=None):
        node = self.nodes.setdefault(
            nid, {"label": nid, "shape": "rect"})
        if label:
            node["label"] = label
        if shape:
            node["shape"] = shape
        return node


def _parse_node_at(text, pos, state_mode=False):
    """Parse one node reference at pos -> (refs, next_pos) or None.
    A ref is (id, label, shape). `&` fan-out yields several refs."""
    node_re = _STATE_NODE_RE if state_mode else _NODE_RE
    refs = []
    while True:
        m = node_re.match(text, pos)
        if not m:
            return None
        nid = m.group("id") or (m.group("id2") if state_mode
                                else None)
        if not nid:
            return None
        label, shape = None, None
        for kind in ("circle", "stadium", "subroutine", "cylinder",
                     "diamond", "rounded", "rect", "flag"):
            if m.group(kind) is not None:
                label, shape = _clean_label(m.group(kind)), kind
                break
        refs.append((nid, label, shape))
        pos = m.end()
        rest = text[pos:].lstrip()
        if rest.startswith("&"):
            pos = text.index("&", pos) + 1
            while pos < len(text) and text[pos].isspace():
                pos += 1
            continue
        return refs, pos


def _edge_kind(token):
    return {"-->": "arrow", "---": "line", "-.->": "dotted-arrow",
            "-.-": "dotted", "==>": "thick-arrow", "<-->": "both",
            "--x": "cross", "--o": "circle-end"}[token]


def _parse_chain(stmt, graph, state_mode=False):
    """Parse one flowchart/state statement into the graph.
    Returns True when the statement was fully consumed."""
    parsed = _parse_node_at(stmt, 0, state_mode)
    if not parsed:
        return False
    refs, pos = parsed
    for nid, label, shape in refs:
        graph.node(nid, label, shape)
    prev = refs
    if not stmt[pos:].strip():
        return True
    while stmt[pos:].strip():
        m = _CONN_RE.match(stmt, pos)
        if not m:
            return False
        if m.group("kind"):
            kind, label = _edge_kind(m.group("kind")), m.group("label")
        elif m.group("ikind"):
            kind = _edge_kind(m.group("ikind"))
            label = m.group("ilabel")
        elif m.group("tlabel") is not None:
            kind, label = "thick-arrow", m.group("tlabel")
        else:
            kind, label = "dotted-arrow", m.group("dlabel")
        parsed = _parse_node_at(stmt, m.end(), state_mode)
        if not parsed:
            return False
        refs, pos = parsed
        for nid, lab, shape in refs:
            graph.node(nid, lab, shape)
        for a, _la, _sa in prev:
            for b, _lb, _sb in refs:
                graph.edges.append(
                    {"from": a, "to": b, "kind": kind,
                     "label": _clean_label(label) if label else ""})
        prev = refs
    return True


# ------------------------------------------------------------------
# Parsers
# ------------------------------------------------------------------

def _parse_graph_body(lines, model, state_mode, direction="TD"):
    graph = _Graph()
    subgraphs = []
    for raw in lines:
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("subgraph"):
            name = line[len("subgraph"):].strip()
            title = _clean_label(name.split("[", 1)[-1].rstrip("]")
                                 if "[" in name else name) or name
            subgraphs.append(title)
            model["warnings"].append(
                f"subgraph {title!r}: boundary not drawn by the subset "
                "renderer; its nodes and edges are rendered ungrouped")
            continue
        if line == "end" and subgraphs:
            subgraphs.pop()
            continue
        if line.split()[0] == "direction" and len(line.split()) == 2 \
                and line.split()[1] in ("TD", "TB", "LR", "RL", "BT"):
            direction = line.split()[1]
            continue
        if state_mode:
            m = _STATE_DECL_RE.match(line)
            if m:
                graph.node(m.group("id"), m.group("desc"))
                continue
        for stmt in line.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.split()[0] in ("classDef", "class", "style",
                                  "linkStyle", "click"):
                model["unparsed"].append(stmt)
                continue
            if state_mode:
                m = _STATE_DESC_RE.match(stmt)
                if m and "--" not in stmt:
                    graph.node(m.group("id"),
                               _clean_label(m.group("desc")))
                    continue
                # Transition label: `A --> B : label` — the label
                # rides after the target node, not the connector.
                tm = re.match(r"^(.*?(?:-->|---)\s*\S+)\s*:\s*(.+)$",
                              stmt)
                if tm:
                    before = len(graph.edges)
                    if _parse_chain(tm.group(1), graph, True):
                        if len(graph.edges) > before:
                            graph.edges[-1]["label"] = _clean_label(
                                tm.group(2))
                        continue
            if not _parse_chain(stmt, graph, state_mode):
                model["unparsed"].append(stmt)
    if state_mode:
        for nid in list(graph.nodes):
            if nid == "[*]":
                graph.nodes[nid] = {"label": "", "shape": "pseudo"}
    model["nodes"] = [dict(id=nid, **graph.nodes[nid])
                       for nid in sorted(graph.nodes)]
    model["edges"] = graph.edges
    model["direction"] = direction


def _parse_pie(lines, model):
    slices = []
    for raw in lines:
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.split()[0] in ("pie", "title") or line == "showData":
            if line.startswith("title"):
                model["title"] = _clean_label(line[5:])
            continue
        m = _PIE_SLICE_RE.match(line)
        if m:
            label = m.group("q") or m.group("bare").strip()
            value = float(m.group("val"))
            if value <= 0:
                model["unparsed"].append(line)
            else:
                slices.append({"label": label, "value": value})
            continue
        model["unparsed"].append(line)
    model["slices"] = slices


def parse_mermaid(src):
    """Parse a Mermaid block into a model dict. Unsupported types
    return a model carrying only the type and the reason — the
    source is never partially mined for facts it cannot support."""
    model = {"type": "unsupported", "head": "", "title": "",
             "direction": "TD", "nodes": [], "edges": [],
             "slices": [], "unparsed": [], "warnings": [],
             "reason": ""}
    src = str(src)
    lines = src.splitlines()
    # YAML frontmatter (--- ... ---): take a title if present.
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for fm in lines[1:i]:
                    if fm.strip().startswith("title:"):
                        model["title"] = _clean_label(
                            fm.strip()[len("title:"):])
                lines = lines[i + 1:]
                break
    mtype, head = diagram_type("\n".join(lines))
    model["type"], model["head"] = mtype, head
    # Skip to the head line; parse what follows it.
    body, seen_head = [], False
    for raw in lines:
        line = raw.strip()
        if not seen_head:
            if line and not line.startswith("%%") \
                    and line.split() and line.split()[0] == head:
                seen_head = True
                rest = line[len(head):].strip()
                if mtype == "flowchart" and rest in (
                        "TD", "TB", "LR", "RL", "BT"):
                    model["direction"] = rest
                elif mtype == "pie" and rest.startswith("title"):
                    model["title"] = _clean_label(rest[5:])
                elif rest and rest != "showData":
                    model["unparsed"].append(rest)
            continue
        body.append(raw)
    if mtype == "flowchart":
        _parse_graph_body(body, model, state_mode=False,
                          direction=model["direction"])
    elif mtype == "state":
        _parse_graph_body(body, model, state_mode=True,
                          direction=model["direction"])
    elif mtype == "pie":
        _parse_pie(body, model)
    else:
        model["reason"] = (
            f"diagram type {head or 'unknown'!r} is outside the "
            "supported subset (flowchart, state diagrams, pie)")
    return model


# ------------------------------------------------------------------
# SVG compilation
# ------------------------------------------------------------------

def _wrap(text, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def _arrowhead(x, y, ux, uy, colour, filled=True):
    """A plain polygon arrowhead at (x, y) pointing along (ux, uy).
    No <defs>/marker ids — nothing to collide across figures."""
    size = 9
    px, py = -uy, ux
    bx, by = x - ux * size, y - uy * size
    fill = colour if filled else "none"
    return (f'<polygon points="{x:.0f},{y:.0f} '
            f'{bx + px * 4:.0f},{by + py * 4:.0f} '
            f'{bx - px * 4:.0f},{by - py * 4:.0f}" '
            f'fill="{fill}" stroke="{colour}" stroke-width="1.2"/>')


def _shape_svg(node, box):
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    shape = node["shape"]
    if shape == "diamond":
        cx, cy = x + w / 2, y + h / 2
        return (f'<polygon points="{cx:.0f},{y:.0f} {x + w:.0f},{cy:.0f} '
                f'{cx:.0f},{y + h:.0f} {x:.0f},{cy:.0f}" '
                f'fill="{_BOX_FILL}" stroke="{_BOX_LINE}"/>')
    if shape == "circle":
        return (f'<ellipse cx="{x + w / 2:.0f}" cy="{y + h / 2:.0f}" '
                f'rx="{w / 2:.0f}" ry="{h / 2:.0f}" '
                f'fill="{_BOX_FILL}" stroke="{_BOX_LINE}"/>')
    if shape == "pseudo":
        return (f'<circle cx="{x + w / 2:.0f}" cy="{y + h / 2:.0f}" '
                f'r="{min(w, h) / 2:.0f}" fill="{_INK}"/>')
    rx = {"rounded": 10, "stadium": 999}.get(shape, 6)
    out = (f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
           f'height="{h:.0f}" rx="{rx if rx != 999 else h / 2:.0f}" '
           f'fill="{_BOX_FILL}" stroke="{_BOX_LINE}"/>')
    if shape == "subroutine":
        for dx in (5, w - 5):
            out += (f'<line x1="{x + dx:.0f}" y1="{y:.0f}" '
                    f'x2="{x + dx:.0f}" y2="{y + h:.0f}" '
                    f'stroke="{_BOX_LINE}"/>')
    if shape == "cylinder":
        out += (f'<ellipse cx="{x + w / 2:.0f}" cy="{y + 5:.0f}" '
                f'rx="{w / 2:.0f}" ry="5" fill="none" '
                f'stroke="{_BOX_LINE}"/>')
    if shape == "flag":
        out = (f'<polygon points="{x:.0f},{y:.0f} {x + w:.0f},{y:.0f} '
               f'{x + w:.0f},{y + h:.0f} {x:.0f},{y + h:.0f} '
               f'{x + 10:.0f},{y + h / 2:.0f}" '
               f'fill="{_BOX_FILL}" stroke="{_BOX_LINE}"/>')
    return out


def _rank_nodes(names, edges):
    """Longest-path ranks with deterministic cycle breaking: a DFS
    in name order marks edges into an ancestor on its own stack as
    back edges; back edges are drawn but do not rank, so a retry
    loop cannot inflate the layout the way naive relaxation does.
    Returns (rank, warnings)."""
    adjacency = {n: [] for n in names}
    for e in edges:
        if e["from"] in adjacency and e["to"] in adjacency:
            adjacency[e["from"]].append(e["to"])
    for n in names:
        adjacency[n] = sorted(set(adjacency[n]))
    back = set()
    colour = {n: 0 for n in names}  # 0 white, 1 on stack, 2 done
    for root in names:
        if colour[root]:
            continue
        stack = [(root, iter(adjacency[root]))]
        colour[root] = 1
        path = [root]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if colour[nxt] == 1:
                    back.add((node, nxt))
                elif colour[nxt] == 0:
                    colour[nxt] = 1
                    stack.append((nxt, iter(adjacency[nxt])))
                    path.append(nxt)
                    advanced = True
                    break
            if not advanced:
                colour[node] = 2
                stack.pop()
                path.pop()
    rank = {n: 0 for n in names}
    for _ in range(len(names) + 1):
        changed = False
        for e in edges:
            if (e["from"], e["to"]) in back:
                continue
            if e["from"] in rank and e["to"] in rank:
                want = rank[e["from"]] + 1
                if rank[e["to"]] < want:
                    rank[e["to"]] = want
                    changed = True
        if not changed:
            break
    warnings = []
    if back:
        warnings.append(
            f"cycle in the diagram: {len(back)} back edge(s) drawn "
            "but not ranked, so the layout stays compact")
    return rank, warnings


def _graph_svg(model, aria):
    nodes = {n["id"]: n for n in model["nodes"]}
    names = sorted(nodes)
    if not names:
        return "", ["empty diagram"]
    direction = model.get("direction", "TD")
    rank, warnings = _rank_nodes(names, model["edges"])
    by_rank = {}
    for n in names:
        by_rank.setdefault(rank[n], []).append(n)
    # Within-rank order: two barycentre sweeps, name tiebreak — a
    # deterministic approximation, not an optimiser.
    order = {r: sorted(ns) for r, ns in by_rank.items()}
    pos = {n: i for r in sorted(order) for i, n in enumerate(order[r])}
    for _sweep in range(2):
        for r in sorted(order):
            def _key(n, _r=r):
                neigh = [pos[e["from"]] for e in model["edges"]
                         if e["to"] == n and rank[e["from"]] < _r]
                neigh += [pos[e["to"]] for e in model["edges"]
                          if e["from"] == n and rank[e["to"]] > _r]
                bary = (sum(neigh) / len(neigh)) if neigh else pos[n]
                return (bary, n)
            order[r] = sorted(order[r], key=_key)
            for i, n in enumerate(order[r]):
                pos[n] = i
    char_w, line_h, pad = 7.2, 15, 8
    # Geometry in (along, cross) space; mapped to (x, y) at the end.
    boxes = {}
    along = pad
    max_rank = max(by_rank)
    rank_span = {}
    for r in range(max_rank + 1):
        cross = pad
        span = 0
        for n in order.get(r, []):
            node = nodes[n]
            if node["shape"] == "pseudo":
                bw = bh = 18
                lines = []
            else:
                lines = _wrap(node["label"], 24)
                bw = max(len(l) for l in lines) * char_w + 2 * pad
                bh = len(lines) * line_h + 2 * pad
                if node["shape"] == "diamond":
                    bw, bh = bw * 1.5, bh * 1.6
                if node["shape"] == "circle":
                    bw = bh = max(bw, bh)
            boxes[n] = {"along": along, "cross": cross,
                        "alen": bh, "clen": bw, "lines": lines}
            cross += bw + 28
            span = max(span, bh)
        rank_span[r] = span
        along += span + 46
    total_along = along - 46 + pad
    total_cross = max(b["cross"] + b["clen"] for b in boxes.values()) + pad
    flip = direction in ("BT", "RL")
    sideways = direction in ("LR", "RL")

    def xy(b):
        a = b["along"] + b["alen"] / 2
        if flip:
            a = total_along - a
        c = b["cross"] + b["clen"] / 2
        return (a, c) if sideways else (c, a)

    def dims(b):
        return (b["alen"], b["clen"]) if sideways else (b["clen"], b["alen"])

    total_w, total_h = (total_along, total_cross) if sideways \
        else (total_cross, total_along)
    out = [f'<svg viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
           f'width="{min(880, total_w):.0f}" role="img" '
           f'aria-label="{html.escape(aria)}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    for e in model["edges"]:
        if e["from"] not in boxes or e["to"] not in boxes:
            continue
        ba, bb = boxes[e["from"]], boxes[e["to"]]
        x1, y1 = xy(ba)
        x2, y2 = xy(bb)
        wa, ha = dims(ba)
        wb, hb = dims(bb)
        # Trim the line to the box edges along its own direction.
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy) or 1
        ux, uy = dx / dist, dy / dist
        ta = min(abs(ux) and wa / 2 / abs(ux) or 1e9,
                 abs(uy) and ha / 2 / abs(uy) or 1e9)
        tb = min(abs(ux) and wb / 2 / abs(ux) or 1e9,
                 abs(uy) and hb / 2 / abs(uy) or 1e9)
        sx, sy = x1 + ux * ta, y1 + uy * ta
        tx, ty = x2 - ux * tb, y2 - uy * tb
        dash = ' stroke-dasharray="5 4"' if "dotted" in e["kind"] else ""
        width = "2.8" if e["kind"] == "thick-arrow" else "1.6"
        out.append(f'<line x1="{sx:.0f}" y1="{sy:.0f}" x2="{tx:.0f}" '
                   f'y2="{ty:.0f}" stroke="{_EDGE}" '
                   f'stroke-width="{width}"{dash}/>')
        heads = []
        if e["kind"] in ("arrow", "dotted-arrow", "thick-arrow",
                         "both"):
            heads.append((tx, ty, ux, uy))
        if e["kind"] == "both":
            heads.append((sx, sy, -ux, -uy))
        for hx, hy, hux, huy in heads:
            out.append(_arrowhead(hx, hy, hux, huy, _EDGE))
        if e["kind"] == "cross":
            cx, cy = tx, ty
            out.append(f'<line x1="{cx - 5:.0f}" y1="{cy - 5:.0f}" '
                       f'x2="{cx + 5:.0f}" y2="{cy + 5:.0f}" '
                       f'stroke="{_EDGE}" stroke-width="1.6"/>'
                       f'<line x1="{cx - 5:.0f}" y1="{cy + 5:.0f}" '
                       f'x2="{cx + 5:.0f}" y2="{cy - 5:.0f}" '
                       f'stroke="{_EDGE}" stroke-width="1.6"/>')
        if e["kind"] == "circle-end":
            out.append(f'<circle cx="{tx:.0f}" cy="{ty:.0f}" r="4.5" '
                       f'fill="{_BOX_FILL}" stroke="{_EDGE}"/>')
        if e["label"]:
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            out.append(
                f'<text x="{mx:.0f}" y="{my - 4:.0f}" fill="{_DIM}" '
                f'font-size="11.5" text-anchor="middle" '
                f'style="paint-order:stroke" stroke="#171512" '
                f'stroke-width="4">{html.escape(e["label"])}</text>')
    for n in names:
        b = boxes[n]
        cx, cy = xy(b)
        w, h = dims(b)
        box = {"x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h}
        out.append(_shape_svg(nodes[n], box))
        lines = b["lines"]
        for i, ln in enumerate(lines):
            ty = cy + (i - (len(lines) - 1) / 2) * line_h + 4
            out.append(f'<text x="{cx:.0f}" y="{ty:.0f}" '
                       f'fill="{_INK}" font-size="12.5" '
                       f'text-anchor="middle">{html.escape(ln)}</text>')
    out.append("</svg>")
    return "".join(out), warnings


def _pie_svg(model):
    slices = model["slices"]
    total = sum(s["value"] for s in slices)
    if not slices or total <= 0:
        return "", ["pie has no positive slices"]
    cx, cy, r = 130, 130, 110
    out = [f'<svg viewBox="0 0 560 260" width="560" role="img" '
           f'aria-label="Pie chart" '
           f'xmlns="http://www.w3.org/2000/svg">']
    if len(slices) == 1:
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" '
                   f'fill="{_PIE_FILLS[0]}"/>')
    else:
        angle = -90.0
        for i, s in enumerate(slices):
            sweep = 360.0 * s["value"] / total
            a1, a2 = math.radians(angle), math.radians(angle + sweep)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            large = 1 if sweep > 180 else 0
            fill = _PIE_FILLS[i % len(_PIE_FILLS)]
            out.append(
                f'<path d="M {cx} {cy} L {x1:.1f} {y1:.1f} '
                f'A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
                f'fill="{fill}" stroke="#171512" stroke-width="1.5"/>')
            angle += sweep
    ly = 34
    for i, s in enumerate(slices):
        fill = _PIE_FILLS[i % len(_PIE_FILLS)]
        pct = 100.0 * s["value"] / total
        val = f'{s["value"]:g}'
        out.append(f'<rect x="280" y="{ly - 11}" width="12" '
                   f'height="12" fill="{fill}"/>')
        out.append(
            f'<text x="300" y="{ly}" fill="{_INK}" font-size="12.5">'
            f'{html.escape(s["label"])} — {html.escape(val)} '
            f'({pct:.1f}%)</text>')
        ly += 22
    out.append("</svg>")
    return "".join(out), []


def mermaid_svg(model):
    """Compile a parsed model to (svg, warnings). An unsupported
    type — or a supported type with nothing drawable — yields ""
    plus the reason, so the caller falls back by name."""
    if model["type"] in ("flowchart", "state"):
        aria = "State diagram" if model["type"] == "state" \
            else "Flowchart"
        return _graph_svg(model, aria)
    if model["type"] == "pie":
        return _pie_svg(model)
    return "", [model.get("reason") or "unsupported diagram type"]


# ------------------------------------------------------------------
# Sanitisation + figure assembly (the renderer interface)
# ------------------------------------------------------------------

_FORBIDDEN_TAG = re.compile(
    r"<\s*script|<\s*foreignobject|javascript:|xlink:href|"
    r"\bhref\s*=|\bon[a-z]+\s*=|<\s*use\b|url\(\s*['\"]?https?:",
    re.IGNORECASE)
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


def sanitize_svg(svg):
    """Return the svg unchanged when it carries no forbidden
    construct, else "". Only TAG SKELETONS are scanned: character
    data is escaped at emission, so a label quoting the text
    `onerror=` is inert text and must not trip the check, while a
    real injected tag is a tag here and does. A raw "<" surviving
    outside any tag means unescaped content — also a trip. The
    generator escapes every label and emits a fixed element
    vocabulary, so a trip means a renderer bug — the caller
    degrades to the named fallback rather than shipping suspect
    markup."""
    if not svg:
        return svg
    skeleton = "".join(_TAG_RE.findall(svg))
    character_data = _TAG_RE.sub("", svg)
    if "<" in character_data or _FORBIDDEN_TAG.search(skeleton):
        return ""
    return svg


_TYPE_NAMES = {"flowchart": "flowchart", "state": "state diagram",
               "pie": "pie chart"}


def figure_html(src):
    """The complete <figure> for one ```mermaid block, plus its
    census info. The source block travels with the figure (the
    block is the source of truth, the SVG its compiled view); an
    unsupported type renders the named unrendered state with the
    source shown as-is — never a broken or empty page region."""
    model = parse_mermaid(src)
    svg, warns = mermaid_svg(model)
    info = {"type": model["head"] or model["type"],
            "rendered": False, "unparsed": list(model["unparsed"])}
    notes = "".join(
        '<p class="caption">Not compiled (outside the supported '
        f'subset): {html.escape(u)}</p>' for u in model["unparsed"])
    notes += "".join(
        f'<p class="caption">{html.escape(w)}</p>'
        for w in model["warnings"] + warns)
    src_block = f'<pre><code>{html.escape(src)}</code></pre>'
    if svg:
        svg = sanitize_svg(svg)
    if svg:
        info["rendered"] = True
        title = f' — {html.escape(model["title"])}' \
            if model["title"] else ""
        return (f'<figure class="mermaidfig"><figcaption>Mermaid '
                f'{_TYPE_NAMES.get(model["type"], "diagram")}{title}'
                ' — compiled at build from the Mermaid block below; '
                f'the block is the source of truth.</figcaption>{svg}'
                '<details><summary>Mermaid source</summary>'
                f'{src_block}</details>{notes}</figure>', info)
    reason = html.escape(
        (warns[0] if warns else model.get("reason")
         or "nothing drawable in the supported subset"))
    return (f'<figure class="mermaidfig"><figcaption>Mermaid '
            f'diagram — not compiled: {reason}. The source block '
            'is shown as-is.</figcaption>'
            f'{src_block}{notes}</figure>', info)


def lift_mermaid(body):
    """Lift every ```mermaid fence out of a page body.

    Returns (body, figures, infos): the body with a placeholder
    paragraph per block, the figure HTML strings in order, and the
    per-block census infos. Bodies without a Mermaid fence come
    back byte-identical with empty lists."""
    figures, infos = [], []

    def _sub(m):
        src = m.group(1)
        fig, info = figure_html(src)
        idx = len(figures)
        figures.append(fig)
        infos.append(info)
        return f"\n\nLENSMERMAIDFIG{idx}\n\n"

    new_body = FENCE_RE.sub(_sub, body)
    return new_body, figures, infos
