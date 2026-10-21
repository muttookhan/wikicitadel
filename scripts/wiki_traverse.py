#!/usr/bin/env python3
"""wiki_traverse.py — the read-only traversal door for agents.

WikiCitadel v1, pattern: Christian Tietze's `ta` CLI
— a purpose-built, read-only CLI over a
plain-text archive, taught to agents via a SKILL.md. Tietze's
mechanic, transferred: the agent-facing door is a small CLI
whose graph moves (read a page, walk neighbours, follow a path)
are verbs, so an agent spends tokens on the graph instead of
on file plumbing — and read-only is a property of the TOOL,
not a policy the agent is asked to respect.

This is the read-side sibling of the gateway
(tools/gateway/): the gateway governs writes by scopes and a
hash-chained ledger; this door governs reads by construction.
It imports no write path, opens every file read-only, and its
command surface contains no mutating verb (a test pins all
three properties, including a checksum proof over a fixture
tree: every command runs, every checksum survives).

Identity + the read rule (the [[notices]] protocol-tier
composition applied to reads; the caller states an admitted
identity with --as, default-deny like the gateway):

  * Admitted identities: owner, agent, galen, hugo, codex,
    chatgpt, coordinator, antigravity — EXAMPLE LIST: a
    deployment configures its own identities in ADMITTED
    below. Anything else is refused before any file is
    touched.
  * The compiled layer (wiki/) and the evaluation registers
    are readable by every admitted identity.
  * The raw layer is gated by the sensitivity register
    (evaluation/sensitivity.json), class by class:
      credential-adjacent — owner only, ever (the class rule
        is "never compiled, never cited"; the door adds
        "never served to another identity");
      export-only        — owner only (the content is never
        compiled; this door does not become the side channel
        around that rule — the export's own compiled source
        page stays readable by all);
      personal,
      family-sensitive   — owner + agent (the owner's agent
        already holds this material under the memory-
        transparency rule); filings-seat identities refused;
      public, internal   — every admitted identity;
      unclassified       — every admitted identity, and the
        read is STAMPED unclassified: the register's state of
        ignorance is surfaced, never silently read as public.
  * Search honours the same gate coarsely: a filings-seat
    identity's search is restricted to the compiled layer
    (scope forced to wiki, and the output says so), because
    ranked snippets cannot be class-filtered after the fact.

The graph is the Lens's graph, not a second invention:
wikilinks typed by the heading they sit under
(tools/lens/lenslib.py SECTION_TYPE_RULES — imported, so the
door and the Lens walk the same typed edges), frontmatter
`links:` declarations, the relation-vocabulary frontmatter
fields (wiki/rules/relation-vocabulary.md, incl. the adopted
`grounds` pair), and `sources:` citation edges.

Commands (every one a read):

    python3 scripts/wiki_traverse.py --as <identity> page <name>
    python3 scripts/wiki_traverse.py --as <identity> source <raw-path>
    python3 scripts/wiki_traverse.py --as <identity> neighbours <page>
        [--type T] [--dir out|in|both]
    python3 scripts/wiki_traverse.py --as <identity> path <from> <to>
        [--max-depth N]
    python3 scripts/wiki_traverse.py --as <identity> census
    python3 scripts/wiki_traverse.py --as <identity> claim [query]
    python3 scripts/wiki_traverse.py --as <identity> cite <page>
    python3 scripts/wiki_traverse.py --as <identity> cite --id c0001
    python3 scripts/wiki_traverse.py --as <identity> search "<query>"
        [--top N] [--scope wiki|raw|all]

<name> resolves by repo-relative path, then by path without
suffix, then by file stem, then by frontmatter title — the
precedence the validator, the search and the Lens all use.
--json switches any command to a JSON rendering of the same
facts. Teaching file: tools/traverse/SKILL.md.

Frozen reads: `--pin <commit>` (a global option, before the
command) resolves EVERY read of the session against that
commit's tree instead of the working tree — the tree is
extracted read-only from `git archive` into a temporary
directory and the working tree is never written, checked
out, or moved. Output is stamped with the resolved commit.
A page edited since the pin reads as its pinned text.

Exit codes: 0 ok · 1 refusal (unadmitted identity, gated raw,
no such page, unresolvable pin) · 2 usage error.
"""
import argparse
import atexit
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# ---------------------------------------------------------------------------
# Identity + sensitivity gate (the read rule, stated in the docstring)
# ---------------------------------------------------------------------------

ADMITTED = ("owner", "agent", "galen", "hugo", "codex", "chatgpt",
            "coordinator", "antigravity")
FULL_RAW = ("owner", "agent")          # personal + family-sensitive
OWNER_ONLY_CLASSES = ("credential-adjacent", "export-only")
OWNER_AGENT_CLASSES = ("personal", "family-sensitive")
OPEN_CLASSES = ("public", "internal")

SENSITIVITY_REL = "evaluation/sensitivity.json"

# Relation-vocabulary frontmatter spellings (wiki/rules/
# relation-vocabulary.md) + the adopted local extension pair
# (grounds / is_grounded_by, a local extension). Forward fields
# assert (page -> target, relation); inverse fields assert
# (target -> page, forward relation).
FORWARD_FIELDS = {
    "supersedes": "supersedes", "cites": "cites",
    "corrects": "corrects", "extends": "extends",
    "contradicts": "contradicts", "derives_from": "derives-from",
    "replaces_part_of": "replaces-part-of", "grounds": "grounds",
}
INVERSE_FIELDS = {
    "superseded_by": "supersedes", "cited_by": "cites",
    "corrected_by": "corrects", "is_grounded_by": "grounds",
}


class Refusal(Exception):
    """A read the door will not perform (exit 1)."""


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_pinned_root(root, pin):
    """Resolve a frozen read: extract the tree at commit `pin`
    into a fresh temporary directory with `git archive` and
    return (pinned_root, commit). The working tree is only ever
    READ (rev-parse + archive); nothing in it is written,
    checked out, or moved. The extraction lives in the OS temp
    area and is removed at exit. An unresolvable pin is a
    Refusal, raised before any page is read."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify",
         pin + "^{commit}"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refusal(f"pin '{pin}' does not resolve to a commit "
                      f"in this tree")
    commit = proc.stdout.strip()
    dest = Path(tempfile.mkdtemp(prefix="wiki-traverse-pin-"))
    tar_path = dest.parent / (dest.name + ".tar")
    proc = subprocess.run(
        ["git", "-C", str(root), "archive", "--output",
         str(tar_path), commit], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refusal(f"could not archive pin '{pin}' "
                      f"({commit}) for a frozen read")
    proc = subprocess.run(
        ["tar", "-xf", str(tar_path), "-C", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refusal(f"could not extract pin '{pin}' "
                      f"({commit}) for a frozen read")
    atexit.register(subprocess.run,
                    ["rm", "-rf", str(dest), str(tar_path)])
    return dest, commit

def validate_mod(root):
    return _load_module("wiki_validate", root / "scripts" / "wiki_validate.py")


def lenslib_mod(root):
    return _load_module("lenslib", root / "tools" / "lens" / "lenslib.py")


def claims_mod(root):
    return _load_module("wiki_claims", root / "scripts" / "wiki_claims.py")


# ---------------------------------------------------------------------------
# Sensitivity classification of a raw path
# ---------------------------------------------------------------------------

def load_sensitivity(root):
    path = root / SENSITIVITY_REL
    if not path.exists():
        return {"assignments": [], "classes": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    classes = {c["id"]: c for c in data.get("classes", [])}
    return {"assignments": data.get("assignments", []), "classes": classes}


def classify_raw(root, rel_path):
    """The sensitivity class of a raw path: the register's
    assignment whose path prefixes it (a directory assignment
    covers its tree), else 'unclassified' — a state of
    ignorance, never a promotion to public."""
    rel = rel_path.replace("\\", "/")
    best = None
    for a in load_sensitivity(root)["assignments"]:
        p = a["path"]
        if rel == p or rel.startswith(p if p.endswith("/") else p + "/"):
            if best is None or len(p) > len(best["path"]):
                best = a
    return best["class"] if best else "unclassified"


def raw_read_permitted(identity, cls):
    if cls in OWNER_ONLY_CLASSES:
        return identity == "owner"
    if cls in OWNER_AGENT_CLASSES:
        return identity in FULL_RAW
    return True  # public / internal / unclassified (stamped)


def require_admitted(identity):
    if identity not in ADMITTED:
        raise Refusal(
            f"identity '{identity}' is not admitted at this door "
            f"(admitted: {', '.join(ADMITTED)}); default is deny")


# ---------------------------------------------------------------------------
# The page graph (the Lens's edges, imported not reinvented)
# ---------------------------------------------------------------------------

def iter_pages(root):
    wiki = root / "wiki"
    if not wiki.exists():
        return []
    return sorted(p for p in wiki.rglob("*.md") if p.is_file())


def page_index(root):
    """{key: rel} resolution keys + {rel: (fields, body, text)}."""
    wv = validate_mod(root)
    lens = lenslib_mod(root)
    pages = {}
    keys = {}
    for p in iter_pages(root):
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, body = wv.parse_frontmatter(text)
        fields = fields or {}
        # The validator's subset parser nulls nested mappings, so
        # the frontmatter `links:` declarations (a nested dict)
        # are taken from the Lens's full YAML parse — the same
        # parse the Lens's own edge table is built from.
        yaml_fm, _b, _t = lens.parse_markdown_file(p)
        if isinstance(yaml_fm.get("links"), dict):
            fields["links"] = yaml_fm["links"]
        pages[rel] = (fields, body, text)
        keys.setdefault(rel, rel)
        keys.setdefault(str(Path(rel).with_suffix("")), rel)
        keys.setdefault(Path(rel).stem, rel)
        title = (fields or {}).get("title")
        if title:
            keys.setdefault(str(title).strip().strip('"'), rel)
    return pages, keys


def resolve_page(keys, name):
    name = name.strip()
    for cand in (name, name[:-3] if name.endswith(".md") else name,
                 Path(name).name, Path(name).stem):
        if cand in keys:
            return keys[cand]
    raise Refusal(f"no page resolves from '{name}'")


def build_edges(root, pages, keys):
    """Typed edges over the compiled layer:
    [{src, dst, kind, relation}] with dst a page rel for
    page-graph edges and 'raw:<path>' for citation edges."""
    lens = lenslib_mod(root)
    wv = validate_mod(root)
    edges = []
    seen = set()

    def add(src, dst, kind, relation):
        key = (src, dst, kind, relation)
        if src != dst and key not in seen:
            seen.add(key)
            edges.append({"src": src, "dst": dst, "kind": kind,
                          "relation": relation})

    for rel, (fields, body, _text) in sorted(pages.items()):
        for target, _a, _label, _h, ltype in lens.extract_wikilinks_typed(body):
            dst = None
            for cand in (target, Path(target).name, Path(target).stem):
                if cand in keys:
                    dst = keys[cand]
                    break
            if dst:
                add(rel, dst, "wikilink", ltype)
        links_fm = fields.get("links")
        if isinstance(links_fm, dict):
            for relation, targets in links_fm.items():
                for t in wv.as_list(targets):
                    dst = keys.get(str(t)) or keys.get(Path(str(t)).name)
                    if dst:
                        add(rel, dst, "typed", str(relation))
        for field, relation in FORWARD_FIELDS.items():
            for t in wv.as_list(fields.get(field)):
                dst = keys.get(str(t)) or keys.get(Path(str(t)).name)
                if dst:
                    add(rel, dst, "typed", relation)
        for field, relation in INVERSE_FIELDS.items():
            for t in wv.as_list(fields.get(field)):
                src = keys.get(str(t)) or keys.get(Path(str(t)).name)
                if src:
                    add(src, rel, "typed", relation)
        for s in wv.as_list(fields.get("sources")):
            s = str(s)
            add(rel, s if s.startswith("raw/") else f"raw:{s}",
                "citation", "cites")
    return edges


def page_graph(root):
    pages, keys = page_index(root)
    edges = build_edges(root, pages, keys)
    return pages, keys, edges


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_page(root, identity, name, as_json):
    pages, keys = page_index(root)
    rel = resolve_page(keys, name)
    fields, body, _text = pages[rel]
    if as_json:
        return {"page": rel, "frontmatter": fields, "body": body}
    head = [f"# {rel}"]
    for k in ("title", "type", "status", "confidence", "stage",
              "work_type"):
        if fields.get(k):
            head.append(f"{k}: {fields[k]}")
    return "\n".join(head) + "\n\n" + body.strip() + "\n"


def cmd_source(root, identity, raw_path, as_json):
    rel = raw_path.replace("\\", "/").lstrip("/")
    if not rel.startswith("raw/") and (root / "raw" / rel).exists():
        rel = "raw/" + rel
    path = root / rel
    if not rel.startswith("raw/") or not path.is_file():
        raise Refusal(f"no raw source at '{raw_path}'")
    cls = classify_raw(root, rel)
    if not raw_read_permitted(identity, cls):
        raise Refusal(
            f"raw read refused for identity '{identity}': {rel} is "
            f"class '{cls}' in the sensitivity register "
            f"(evaluation/sensitivity.json)")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if as_json:
        return {"source": rel, "sensitivity": cls, "text": text}
    stamp = "" if cls != "unclassified" else \
        " [UNCLASSIFIED — no class on the register; not thereby public]"
    return f"# {rel}\nsensitivity: {cls}{stamp}\n\n{text}"


def _edge_lines(edges):
    return [f"{e['src']} -[{e['relation']} ({e['kind']})]-> {e['dst']}"
            for e in edges]


def cmd_neighbours(root, identity, name, etype, direction, as_json):
    _pages, keys, edges = page_graph(root)
    rel = resolve_page(keys, name)
    out = []
    for e in edges:
        if etype and e["relation"] != etype:
            continue
        if direction in ("out", "both") and e["src"] == rel:
            out.append(e)
        elif direction in ("in", "both") and e["dst"] == rel:
            out.append(e)
    if as_json:
        return {"page": rel, "neighbours": out}
    lines = [f"neighbours of {rel} (direction: {direction}"
             + (f", type: {etype}" if etype else "") + f") — {len(out)}"]
    lines += _edge_lines(out)
    return "\n".join(lines) + "\n"


def cmd_path(root, identity, a, b, max_depth, as_json):
    _pages, keys, edges = page_graph(root)
    src, dst = resolve_page(keys, a), resolve_page(keys, b)
    adj = defaultdict(list)
    uadj = defaultdict(set)
    for e in edges:
        if e["kind"] == "citation":
            continue
        adj[e["src"]].append(e)
        uadj[e["src"]].add(e["dst"])
        uadj[e["dst"]].add(e["src"])

    def bfs(graph, directed):
        prev = {src: None}
        q = deque([(src, 0)])
        while q:
            node, d = q.popleft()
            if node == dst:
                break
            if d >= max_depth:
                continue
            nxt = graph[node] if directed else \
                [{"dst": n, "relation": "—"} for n in sorted(graph[node])]
            for e in nxt:
                if e["dst"] not in prev:
                    prev[e["dst"]] = (node, e.get("relation"))
                    q.append((e["dst"], d + 1))
        if dst not in prev:
            return None
        chain = []
        node = dst
        while node is not None:
            chain.append(node)
            node = prev[node][0] if prev[node] else None
        chain.reverse()
        rels = []
        node = dst
        while prev[node] is not None:
            rels.append(prev[node][1])
            node = prev[node][0]
        rels.reverse()
        return chain, rels

    found = bfs(adj, True)
    note = None
    if not found:
        u = bfs(uadj, False)
        note = ("no directed path; an undirected connection exists "
                f"({' -> '.join(u[0])})" if u else
                f"no connection within depth {max_depth}, directed "
                "or undirected")
    if as_json:
        return {"from": src, "to": dst,
                "path": found[0] if found else None,
                "relations": found[1] if found else None, "note": note}
    if not found:
        return f"path {src} -> {dst}: none — {note}\n"
    chain, rels = found
    parts = [chain[0]]
    for r, node in zip(rels, chain[1:]):
        parts.append(f"-[{r}]-> {node}")
    return f"path {src} -> {dst} ({len(rels)} step(s)):\n  " + \
        "\n  ".join(parts) + "\n"


def cmd_census(root, identity, as_json):
    pages, _keys, edges = page_graph(root)
    by_relation = Counter(e["relation"] for e in edges)
    by_kind = Counter(e["kind"] for e in edges)
    touched = set()
    for e in edges:
        touched.add(e["src"])
        if e["kind"] != "citation":
            touched.add(e["dst"])
    orphans = sorted(set(pages) - touched)
    result = {"pages": len(pages), "edges": len(edges),
              "by_relation": dict(sorted(by_relation.items())),
              "by_kind": dict(sorted(by_kind.items())),
              "orphans": orphans}
    if as_json:
        return result
    lines = [f"census: {len(pages)} pages · {len(edges)} edges",
             "by relation:"]
    lines += [f"  {r}: {n}" for r, n in sorted(by_relation.items())]
    lines.append("by kind:")
    lines += [f"  {k}: {n}" for k, n in sorted(by_kind.items())]
    lines.append(f"orphan pages (no edges): {len(orphans)}")
    lines += [f"  {o}" for o in orphans]
    return "\n".join(lines) + "\n"


def cmd_claim(root, identity, query, as_json):
    wc = claims_mod(root)
    outcomes = wc.load_outcomes()
    by_page = defaultdict(list)
    for o in outcomes:
        by_page[o.get("page")].append(o)
    rows = []
    for p, fields, _body in wc.claim_pages():
        rel = p.relative_to(root).as_posix()
        claim = str(fields.get("claim") or "").strip()
        if query and query.lower() not in claim.lower() \
                and query.lower() not in rel.lower():
            continue
        recs = by_page.get(rel, [])
        rows.append({"page": rel, "claim": claim,
                     "status": wc.status_for(recs),
                     **{k: wc.counters_for(recs)[k]
                        for k in ("outcome_n", "outcome_supports",
                                  "outcome_contradicts")}})
    if as_json:
        return {"claims": rows}
    lines = [f"claim pages: {len(rows)}"]
    for r in rows:
        lines.append(f"- {r['page']} [{r['status']}; outcomes "
                     f"{r['outcome_n']} = +{r['outcome_supports']}"
                     f"/-{r['outcome_contradicts']}]")
        lines.append(f"    {r['claim']}")
    return "\n".join(lines) + "\n"


def cmd_cite(root, identity, page_name, cite_id, as_json):
    lock_path = root / "evaluation" / "citation-lockfile.json"
    if not lock_path.exists():
        raise Refusal("no citation lockfile in this tree")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    cites = lock.get("citations", [])
    if cite_id:
        cites = [c for c in cites if c.get("id") == cite_id]
        if not cites:
            raise Refusal(f"no citation '{cite_id}' in the lockfile")
    else:
        _pages, keys = page_index(root)
        rel = resolve_page(keys, page_name)
        cites = [c for c in cites if c.get("page") == rel]
    out = []
    for c in cites:
        src = c.get("source", "")
        cls = classify_raw(root, src) if src.startswith("raw/") \
            else "unclassified"
        entry = {"id": c.get("id"), "page": c.get("page"),
                 "claim": c.get("claim"), "source": src,
                 "range": c.get("range"),
                 "quote": (c.get("selector") or {}).get("exact"),
                 "sensitivity": cls}
        if not raw_read_permitted(identity, cls):
            entry["quote"] = None
            entry["refused"] = (f"verbatim passage withheld for "
                                f"identity '{identity}': source is "
                                f"class '{cls}'")
        out.append(entry)
    if as_json:
        return {"lockfile_generated": lock.get("generated"),
                "citations": out}
    lines = [f"citations (lockfile of {lock.get('generated')}): "
             f"{len(out)}"]
    for e in out:
        lines.append(f"- {e['id']} · {e['page']} · {e['source']} "
                     f"lines {e['range']}")
        lines.append(f"    claim: {e['claim']}")
        if e["quote"]:
            lines.append(f"    verbatim: {e['quote']}")
        else:
            lines.append(f"    {e.get('refused', 'no quote recorded')}")
    return "\n".join(lines) + "\n"


def cmd_search(root, identity, query, top, scope):
    effective = scope
    note = None
    if identity not in FULL_RAW and scope != "wiki":
        effective = "wiki"
        note = (f"scope restricted to the compiled layer for "
                f"identity '{identity}' (the sensitivity gate: "
                f"ranked raw snippets cannot be class-filtered)")
    cmd = [sys.executable, str(root / "scripts" / "wiki_search.py"),
           query, "--top", str(top), "--scope", effective]
    proc = subprocess.run(cmd, cwd=root, capture_output=True,
                          text=True)
    out = proc.stdout
    if note:
        out = f"[{note}]\n" + out
    if proc.returncode != 0:
        raise Refusal("wiki_search.py failed: " +
                      (proc.stderr.strip().splitlines() or [""])[-1])
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="The read-only traversal door: page reads, "
                    "typed-edge walks, claims, verbatim citations, "
                    "search. No command writes anything.")
    ap.add_argument("--as", dest="identity", required=True,
                    help="admitted identity (see module docstring)")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repo root (default: this tool's repo)")
    ap.add_argument("--pin", default=None,
                    help="freeze the session at this commit: all "
                         "reads resolve against its tree (via a "
                         "read-only git archive extraction); the "
                         "working tree is never written")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("page", help="print a compiled page")
    pp.add_argument("name")
    pp.add_argument("--json", action="store_true")

    sp = sub.add_parser("source", help="print a raw source (gated)")
    sp.add_argument("path")
    sp.add_argument("--json", action="store_true")

    np_ = sub.add_parser("neighbours", help="typed edges of a page")
    np_.add_argument("name")
    np_.add_argument("--type")
    np_.add_argument("--dir", choices=("out", "in", "both"),
                     default="both")
    np_.add_argument("--json", action="store_true")

    tp = sub.add_parser("path", help="shortest directed path")
    tp.add_argument("from_page")
    tp.add_argument("to_page")
    tp.add_argument("--max-depth", type=int, default=6)
    tp.add_argument("--json", action="store_true")

    xp = sub.add_parser("census", help="typed-edge census")
    xp.add_argument("--json", action="store_true")

    kp = sub.add_parser("claim", help="claim pages + status")
    kp.add_argument("query", nargs="?", default=None)
    kp.add_argument("--json", action="store_true")

    cp = sub.add_parser("cite", help="verbatim cited passages")
    cp.add_argument("page", nargs="?", default=None)
    cp.add_argument("--id")
    cp.add_argument("--json", action="store_true")

    qp = sub.add_parser("search", help="delegate to wiki_search.py")
    qp.add_argument("query")
    qp.add_argument("--top", type=int, default=10)
    qp.add_argument("--scope", choices=("wiki", "raw", "all"),
                    default="all")

    args = ap.parse_args(argv)
    root = args.root
    pin_commit = None
    try:
        require_admitted(args.identity)
        if args.pin:
            root, pin_commit = resolve_pinned_root(root, args.pin)
        if args.cmd == "page":
            out = cmd_page(root, args.identity, args.name, args.json)
        elif args.cmd == "source":
            out = cmd_source(root, args.identity, args.path,
                             args.json)
        elif args.cmd == "neighbours":
            out = cmd_neighbours(root, args.identity, args.name,
                                 args.type, args.dir, args.json)
        elif args.cmd == "path":
            out = cmd_path(root, args.identity, args.from_page,
                           args.to_page, args.max_depth, args.json)
        elif args.cmd == "census":
            out = cmd_census(root, args.identity, args.json)
        elif args.cmd == "claim":
            out = cmd_claim(root, args.identity, args.query,
                            args.json)
        elif args.cmd == "cite":
            if not args.page and not args.id:
                ap.error("cite needs a page name or --id")
            out = cmd_cite(root, args.identity, args.page, args.id,
                           args.json)
        elif args.cmd == "search":
            out = cmd_search(root, args.identity, args.query,
                             args.top, args.scope)
        else:  # pragma: no cover
            return 2
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if pin_commit:
        stamp = f"[pinned read: commit {pin_commit}]"
        if isinstance(out, dict):
            out = {"pin": pin_commit, **out}
        else:
            out = stamp + "\n" + out
    if isinstance(out, dict):
        print(json.dumps(out, indent=1))
    else:
        print(out, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
