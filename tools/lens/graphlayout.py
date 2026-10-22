"""Deterministic hierarchical layout for the Lens graph (W2).

The build-list item names the @hpcc-js/wasm-graphviz route: run
Graphviz's `dot` hierarchical layout (via the WASM build of
Graphviz) at build time so the graph's shape is reproducible
byte-for-byte for the same input -- the property the citation /
provenance graphs need for reviewable diffs.

ENGINE REALITY (checked 2026-10-22, stated plainly): that engine
is NOT available on this machine. There is no `dot`/`neato`
binary on PATH, no Python `graphviz` module, and
@hpcc-js/wasm-graphviz — though published on npm (version 1.30.0
at check time) — is not vendored or installed anywhere in the
tree, and installs are out of bounds tonight. So the WASM-Graphviz route is DOORED: the
day the package is vendored (or a `dot` binary is approved), an
adapter can feed this module's inputs to it behind the same
interface (`hierarchical_layout` -> positions + report) and the
artefact's `engine` field will say so.

What ships instead is the house engine in this file: a clean-room
implementation of the layered ("hierarchical") drawing method
published by Sugiyama, Tagawa & Toda ("Methods for Visual
Understanding of Hierarchical Systems", IEEE Trans. Systems, Man
and Cybernetics, 1981) in the form Graphviz's dot implements
(Gansner, Koutsofios, North & Vo, "A Technique for Drawing
Directed Graphs", IEEE Trans. Software Engineering, 1993): the
four dot phases -- cycle removal, rank assignment, ordering by
barycenter sweeps, coordinate assignment -- written from the
papers' descriptions. NO Graphviz code is used (Graphviz is
EPL-licensed; the licence route for this item is clean
re-implementation of the published algorithms). The artefact
names this engine honestly as "house-layered (Sugiyama/dot
method)"; it never claims to be Graphviz.

Deliberate simplifications vs dot, stated rather than hidden:
  * No dummy vertices: an edge spanning several ranks is drawn
    straight across them instead of being routed through dummy
    nodes. Ordering therefore only minimises crossings between
    ADJACENT ranks.
  * Ranks are horizontal layers (rank 0 at the top), coordinates
    on the same 1000 x 660 canvas the force layout uses.
  * Coordinate assignment is the simple centred form: within a
    rank, nodes spread evenly around the canvas centre at a unit
    derived from the widest rank. dot's network-simplex x
    coordinates are not imitated.

DETERMINISM (the item's whole point): every iteration is over
sorted node/edge lists, every tie-break is stated in code, the
sweep count is the constant SWEEPS below, and no wall clock,
randomness, or hash-order input exists anywhere in the module.
Same node set + same directed edge set -> byte-identical
positions, on any machine, in any process.

INPUT: the DIRECTED link graph -- the build's own typed edge
table restricted to the pairs it already treats as direct links
(kinds "wikilink" / "typed", both endpoints graph nodes,
self-loops dropped, duplicate pairs collapsed). Hierarchy
follows link direction: a page sits below the pages that link
to it. This differs from the seeded force layout by design --
the force layout runs over the undirected weighted relation
table; this option runs over directed links only, which is the
graph whose diffs are reviewed (citations / provenance).

COMPOSITION RULES (stated here, implemented by the client from
this module's outputs):
  * Semantic zoom: a community supernode's hierarchical position
    is the CENTROID of its member pages' hierarchical positions
    -- the same rule lenslib.graph_zoom_levels applies to the
    force layout; build_lens computes it by running that very
    function over these positions and shipping the centroids.
  * As-of scrubber: positions are computed over the FULL graph,
    exactly as the force layout's are. A page that did not exist
    at the scrub date simply is not drawn; its position is never
    recomputed per date.

Interface (what build_lens consumes):

  hierarchical_layout(node_ids, directed_edges, width=1000,
                      height=660) -> (positions, report)
      positions: {node_id: [x, y]} rounded to 0.1, covering
      exactly the node set.
      report: {"ranks": int, "rank_sizes": [int],
               "reversed_edges": [[a, b], ...] (the input pairs
               reversed to break cycles, sorted),
               "crossings": int (adjacent-rank crossings of the
               final ordering), "sweeps": SWEEPS,
               "directed_edges": int (after dedupe/filtering),
               "dag_edges": int}
"""

from collections import defaultdict
from heapq import heapify, heappop, heappush

# Fixed by the method, never by the clock: dot's barycenter
# sweeps run a bounded number of passes; 24 is this engine's
# constant, applied identically to every input.
SWEEPS = 24

MARGIN_X = 60.0
MARGIN_Y = 50.0

ENGINE_NAME = "house-layered (Sugiyama/dot method)"
CREDIT = ("Layered drawing method: Sugiyama, Tagawa & Toda 1981; "
          "dot's rank/order phases: Gansner et al. 1993. Clean-room "
          "house implementation -- not Graphviz (EPL) and not the "
          "doored @hpcc-js/wasm-graphviz route.")
RULES = ("Ranks by longest path over the directed link graph "
         "(cycles broken by DFS back-edge reversal, listed in "
         "reversed_edges); within-rank order by barycenter sweeps "
         "(SWEEPS=24, best-crossing ordering kept); a community's "
         "position is the centroid of its members' positions; "
         "positions computed over the full graph -- the As-of "
         "filter only hides pages, never re-layouts.")


def _break_cycles(nodes, edge_set):
    """DFS back-edge reversal. Nodes are visited in sorted
    order, neighbours in sorted order; an edge to a node on the
    current DFS stack (grey) is a back edge and is reversed.
    Returns (dag_edges, reversed_edges), both sorted lists of
    (a, b) pairs in the direction the DAG keeps."""
    succ = {n: [] for n in nodes}
    for a, b in edge_set:
        succ[a].append(b)  # edge_set sorted -> adjacency sorted
    white, grey, black = 0, 1, 2
    colour = {n: white for n in nodes}
    dag = []
    reversed_edges = []
    for start in nodes:
        if colour[start] != white:
            continue
        colour[start] = grey
        stack = [(start, 0)]
        while stack:
            node, idx = stack[-1]
            if idx < len(succ[node]):
                stack[-1] = (node, idx + 1)
                nxt = succ[node][idx]
                if colour[nxt] == grey:
                    reversed_edges.append((node, nxt))
                    dag.append((nxt, node))
                elif colour[nxt] == white:
                    colour[nxt] = grey
                    dag.append((node, nxt))
                    stack.append((nxt, 0))
                else:
                    dag.append((node, nxt))
            else:
                colour[node] = black
                stack.pop()
    return sorted(dag), sorted(reversed_edges)


def _assign_ranks(nodes, dag_edges):
    """Longest-path rank assignment over the DAG: a node's rank
    is 1 + the longest directed path ending at it (sources and
    isolated nodes: rank 0). Kahn's algorithm with a sorted
    ready heap, so the traversal order is input-order-free."""
    succ = {n: [] for n in nodes}
    indeg = {n: 0 for n in nodes}
    for a, b in dag_edges:
        succ[a].append(b)
        indeg[b] += 1
    rank = {n: 0 for n in nodes}
    ready = [n for n in nodes if indeg[n] == 0]
    heapify(ready)
    while ready:
        u = heappop(ready)
        for v in succ[u]:
            if rank[u] + 1 > rank[v]:
                rank[v] = rank[u] + 1
            indeg[v] -= 1
            if indeg[v] == 0:
                heappush(ready, v)
    return rank


def _count_crossings(orders, dag_edges, rank_of):
    """Crossings between adjacent ranks only (no dummy vertices,
    so long edges are not counted -- the stated simplification).
    For each adjacent rank pair, edges are sorted by the upper
    endpoint's position and crossings are the inversions in the
    lower endpoints' position sequence."""
    pos = {}
    for row in orders:
        for i, n in enumerate(row):
            pos[n] = i
    by_rank = defaultdict(list)
    for a, b in dag_edges:
        if rank_of[b] == rank_of[a] + 1:
            by_rank[rank_of[a]].append((pos[a], pos[b]))
    total = 0
    for pairs in by_rank.values():
        pairs.sort()
        seq = [pb for _, pb in pairs]
        for i in range(len(seq)):
            si = seq[i]
            for j in range(i + 1, len(seq)):
                if si > seq[j]:
                    total += 1
    return total


def _order_ranks(nodes, dag_edges, rank_of, nranks):
    """Within-rank ordering: start from node-id order, then
    SWEEPS barycenter passes (down then up per sweep), keeping
    the best-crossing ordering seen (strict improvement only, so
    ties keep the earlier ordering). A node's barycenter is the
    mean position of its DAG neighbours in the adjacent rank;
    a node with no neighbour there keeps its current index.
    Remaining ties break by current index, then node id."""
    orders = [[] for _ in range(nranks)]
    for n in nodes:  # nodes sorted -> initial order is id order
        orders[rank_of[n]].append(n)
    preds = defaultdict(list)
    succs = defaultdict(list)
    for a, b in dag_edges:
        succs[a].append(b)
        preds[b].append(a)

    def sweep_row(row, neighbour_map, ref_pos):
        idx = {n: i for i, n in enumerate(row)}

        def key(n):
            ns = [ref_pos[m] for m in neighbour_map.get(n, ())
                  if m in ref_pos]
            bary = sum(ns) / len(ns) if ns else float(idx[n])
            return (bary, idx[n], n)

        return sorted(row, key=key)

    best = [list(r) for r in orders]
    best_x = _count_crossings(orders, dag_edges, rank_of)
    cur = orders
    for _ in range(SWEEPS):
        for r in range(1, nranks):
            ref = {n: i for i, n in enumerate(cur[r - 1])}
            cur[r] = sweep_row(cur[r], preds, ref)
        for r in range(nranks - 2, -1, -1):
            ref = {n: i for i, n in enumerate(cur[r + 1])}
            cur[r] = sweep_row(cur[r], succs, ref)
        x = _count_crossings(cur, dag_edges, rank_of)
        if x < best_x:
            best_x = x
            best = [list(r) for r in cur]
    return best, best_x


def hierarchical_layout(node_ids, directed_edges, width=1000,
                        height=660):
    """The layered layout. See the module docstring for the
    method, the input contract, and the determinism rules."""
    nodes = sorted(set(node_ids))
    node_set = set(nodes)
    edge_set = sorted({(a, b) for a, b in directed_edges
                       if a in node_set and b in node_set
                       and a != b})
    dag_edges, reversed_edges = _break_cycles(nodes, edge_set)
    rank_of = _assign_ranks(nodes, dag_edges)
    nranks = (max(rank_of.values()) + 1) if nodes else 0
    orders, crossings = _order_ranks(nodes, dag_edges, rank_of,
                                     nranks)
    widest = max((len(r) for r in orders), default=0)
    unit = (width - 2 * MARGIN_X) / widest if widest else 0.0
    positions = {}
    for r, row in enumerate(orders):
        if nranks == 1:
            y = height / 2.0
        else:
            y = MARGIN_Y + r * (height - 2 * MARGIN_Y) / (nranks - 1)
        for j, n in enumerate(row):
            x = width / 2.0 + (j - (len(row) - 1) / 2.0) * unit
            positions[n] = [round(x, 1), round(y, 1)]
    report = {
        "ranks": nranks,
        "rank_sizes": [len(r) for r in orders],
        "reversed_edges": [[a, b] for a, b in reversed_edges],
        "crossings": crossings,
        "sweeps": SWEEPS,
        "directed_edges": len(edge_set),
        "dag_edges": len(dag_edges),
    }
    return positions, report
