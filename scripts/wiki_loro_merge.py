#!/usr/bin/env python3
"""Loro merge-rules pattern half — moveable tree / LWW map /
shallow snapshot for index/outline STATE.

Marathon R12 lane BB (ideas board line 185, Round 10 RB research,
Tier A): the Loro CRDT family's merge rules, restated as a
PATTERN in our own words and implemented with stdlib only.
PATTERN ONLY, stated on its face: this machinery operates on a
declared outline-state value (JSON) supplied to it or held in
the seed register evaluation/loro-merge-rules.json. It does NOT
change the wiki's write topology — git remains the only sync /
write layer for wiki content (see scripts/wiki_sync.py), no page
or index file is read or written by this tool, and no CRDT
library is imported or vendored.

The pattern, as data + machinery:
  - LWW map: each key carries {value, counter, actor, deleted}.
    Merge keeps, per key, the entry with the greater stamp
    (counter, then actor, compared lexicographically); a winning
    tombstone (deleted=true) removes the key from the live view
    but stays in the merged state so the deletion can still win
    against older writes elsewhere.
  - Moveable tree: each node carries {parent, title-stamp...}
    as an LWW entry plus a list of move operations
    {node, parent, counter, actor}. Merge unions the moves,
    replays them in stamp order over the base parents, and a
    move that would create a cycle (moving a node under itself
    or a descendant) or names a missing node/parent LOSES: the
    node keeps its prior parent. Deterministic on every machine.
  - Shallow snapshot: {roots, per-node {parent, child_count,
    subtree_hash}, map_keys, state_hash} — the outline's shape
    and hashes WITHOUT inlining nested child lists or values,
    so two states can be compared cheaply before a full merge.

Commands: check (validate the seed register) / merge (two state
JSON files -> merged state JSON) / snapshot (state JSON file ->
shallow snapshot JSON). Exit 0 ok; 1 invalid on check/merge;
2 usage error. Stdlib only, no network.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "loro-merge-rules.json"
RULES = ["lww-map: per key, greater (counter, actor) stamp wins; "
         "a winning tombstone deletes the live key",
         "moveable-tree: moves replay in (counter, actor) order; "
         "a cycle-forming or dangling move loses, prior parent kept",
         "shallow-snapshot: roots + per-node parent/child_count/"
         "subtree_hash + map key list + state_hash; no inlined "
         "children, no values"]


def _stamp(entry):
    return (entry.get("counter", 0), str(entry.get("actor", "")))


def merge_lww_map(a, b):
    """Merge two LWW maps ({key: entry}) deterministically."""
    out = {}
    for key in sorted(set(a) | set(b)):
        ea, eb = a.get(key), b.get(key)
        if ea is None:
            out[key] = dict(eb)
        elif eb is None:
            out[key] = dict(ea)
        else:
            out[key] = dict(ea if _stamp(ea) >= _stamp(eb) else eb)
    return out


def live_map(m):
    """The live view of an LWW map: non-tombstoned key -> value."""
    return {k: e.get("value") for k, e in sorted(m.items())
            if not e.get("deleted")}


def merge_tree(base_parents, moves_a, moves_b):
    """Replay the union of two move lists over base parents.

    Returns (parents, rejected) where rejected lists the losing
    moves with their reason (cycle / missing). A move is a cycle
    iff its target parent is the moved node itself or one of the
    node's current descendants.
    """
    parents = dict(base_parents)
    moves = sorted(list(moves_a) + list(moves_b),
                   key=lambda m: (m.get("counter", 0),
                                  str(m.get("actor", "")),
                                  str(m.get("node", ""))))
    rejected = []
    for m in moves:
        node, parent = m.get("node"), m.get("parent")
        if node not in parents or (parent is not None
                                   and parent not in parents):
            rejected.append({"move": m, "reason": "missing node or parent"})
            continue
        if parent is not None and _would_cycle(parents, node, parent):
            rejected.append({"move": m, "reason": "cycle"})
            continue
        parents[node] = parent
    return parents, rejected


def _would_cycle(parents, node, new_parent):
    """Moving `node` under `new_parent` cycles iff new_parent is
    node itself or currently sits inside node's subtree, i.e.
    walking up from new_parent reaches node."""
    cur, seen = new_parent, set()
    while cur is not None and cur not in seen:
        if cur == node:
            return True
        seen.add(cur)
        cur = parents.get(cur)
    return False


def merge_state(a, b):
    """Merge two outline states {parents, moves, map}."""
    base = dict(a.get("parents") or {})
    # Nodes known to either side start from a's parents, then any
    # node only b knows is added with b's parent as its base.
    for n, p in (b.get("parents") or {}).items():
        base.setdefault(n, p)
    parents, rejected = merge_tree(base, a.get("moves") or [],
                                   b.get("moves") or [])
    return {"parents": parents,
            "moves": list(a.get("moves") or []) + list(b.get("moves") or []),
            "map": merge_lww_map(a.get("map") or {}, b.get("map") or {}),
            "rejected_moves": rejected}


def _subtree_hash(node, parents, live):
    children = sorted(n for n, p in parents.items() if p == node)
    payload = {"node": node, "title": live.get(node),
               "children": [_subtree_hash(c, parents, live)
                            for c in children]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def shallow_snapshot(state):
    """The shallow shape: roots, per-node parent/child_count/
    subtree_hash, live map KEYS (not values), and a state hash.
    No nested child lists are inlined."""
    parents = state.get("parents") or {}
    live = live_map(state.get("map") or {})
    nodes = {}
    for n in sorted(parents):
        nodes[n] = {"parent": parents[n],
                    "child_count": sum(1 for p in parents.values()
                                       if p == n),
                    "subtree_hash": _subtree_hash(n, parents, live)}
    snap = {"roots": sorted(n for n, p in parents.items() if p is None),
            "nodes": nodes, "map_keys": sorted(live)}
    snap["state_hash"] = hashlib.sha256(
        json.dumps(snap, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()
    return snap


def load_register(path=None):
    p = Path(path) if path else REGISTER
    if not p.is_file():
        return None, [f"register missing: {p}"]
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"register is not valid JSON ({e})"]
    errors = []
    if obj.get("kind") != "loro-merge-rules":
        errors.append("kind must be 'loro-merge-rules'")
    if obj.get("pattern_only") is not True:
        errors.append("pattern_only must be true (stated on its face)")
    for r in RULES:
        head = r.split(":")[0]
        if not any(str(x).startswith(head) for x in obj.get("rules", [])):
            errors.append(f"rules missing the {head!r} rule")
    st = obj.get("state")
    if not isinstance(st, dict) or not all(
            isinstance(st.get(k), dict) for k in ("parents", "map")):
        errors.append("state must carry dict 'parents' and dict 'map'")
    return obj, errors


def _load_state(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Loro merge-rules pattern half (pattern only).")
    sub = ap.add_subparsers(dest="command")
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    pm = sub.add_parser("merge"); pm.add_argument("a"); pm.add_argument("b")
    pm.add_argument("--json", action="store_true")
    ps = sub.add_parser("snapshot"); ps.add_argument("state")
    args = ap.parse_args(argv)
    cmd = args.command or "check"
    if cmd == "check":
        _o, errors = load_register(args.register)
        for e in errors:
            print(f"loro-merge: {e}", file=sys.stderr)
        print(f"loro-merge: register {'INVALID' if errors else 'valid'} "
              "(pattern only; write topology unchanged)")
        return 1 if errors else 0
    if cmd == "merge":
        try:
            merged = merge_state(_load_state(args.a), _load_state(args.b))
        except (OSError, json.JSONDecodeError) as e:
            print(f"loro-merge: cannot merge: {e}", file=sys.stderr)
            return 1
        print(json.dumps(merged, indent=2, sort_keys=True,
                         ensure_ascii=False))
        return 0
    snap = shallow_snapshot(_load_state(args.state))
    print(json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
