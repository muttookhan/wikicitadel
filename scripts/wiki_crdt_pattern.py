#!/usr/bin/env python3
"""Automerge CRDT pattern half — document/merge PATTERN for
small structured registers + offline draft state
(Marathon R12 lane BA).

Pattern: Automerge (Kleppmann et al.) — a JSON-like document
edited independently in more than one place and merged
without a central coordinator, convergence guaranteed by
the merge rules rather than by locking. Pattern only,
re-implemented in our own stdlib code; no Automerge code,
format or text is used.

HARD BOUNDARY, STATED ON ITS FACE: this is PATTERN
MACHINERY ONLY. The wiki's write topology is NOT changed
by anything here: wiki content still has exactly one
writing path, no multi-master writes against wiki content
exist or are enabled, and no command in this tool reads or
writes a wiki page or a standing register. The machinery
operates on small STRUCTURED REGISTER-SHAPED documents —
JSON values of the register shape below — in files a
caller names explicitly (tests use temp files), and on
OFFLINE DRAFT STATE: a draft is a list of not-yet-merged
operations an editor accumulated while offline, which can
be applied to a document or merged with another draft's
operations when back online. It demonstrates the merge
rules; it wires them to nothing.

THE REGISTER SHAPE — a document is
  {"kind": "crdt-register-document", "registers": {
      <register-name>: {"kind": "lww-map" | "add-wins-set",
                        "entries": {...}}, ...}}
An lww-map entry is {"value": <any JSON>, "clock": int,
"actor": str, "deleted": bool}: a key set or tombstoned by
the operation with the highest (clock, actor) stamp wins —
last-writer-wins per key, deterministically, the actor id
breaking clock ties so every replica orders two concurrent
operations identically. A tombstone is an operation like
any other: a newer set revives the key, an older set does
not beat a newer tombstone. An add-wins-set entry is
{"members": {<member>: {"clock": int, "actor": str}},
"removed": {<member>: {"clock": int, "actor": str}}}:
a member is present when its newest add stamp beats its
newest remove stamp (add-wins under concurrency: an add
and a remove at the same clock keep the member).

OPERATIONS are data: {"op": "set"|"delete", "register",
"key", "value"?, "clock", "actor"} for lww-maps and
{"op": "add"|"remove", "register", "member", "clock",
"actor"} for add-wins-sets. apply_op returns a NEW document
(the input is never mutated); merge(a, b) merges two
documents key-wise and member-wise by the same stamps.
The properties that make this a CRDT pattern are pinned by
the tests: merge is commutative, associative and idempotent
on documents, and applying the same operation set in any
order converges to the same document.

Commands:
  check <doc.json>            validate a document's shape
  merge <a.json> <b.json>     print the merged document
      [--out FILE]
  apply <doc.json> <ops.json> print the document after the
      offline draft's operations [--out FILE]
  demo                        print a deterministic worked
                              example (two offline drafts
                              of one register, merged)
Exit 0 ok · 1 invalid document on check · 2 usage error.
Stdlib only, no network, no model calls.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "evaluation" / "crdt-pattern-register.json"
DOC_KIND = "crdt-register-document"
REGISTER_KINDS = ("lww-map", "add-wins-set")


# ------------------------------------------------------------ shape

def new_document():
    return {"kind": DOC_KIND, "registers": {}}


def validate_document(doc):
    """Shape findings; [] means a well-formed register
    document under this pattern."""
    errors = []
    if not isinstance(doc, dict):
        return ["document is not a JSON object"]
    if doc.get("kind") != DOC_KIND:
        errors.append(f"kind must be {DOC_KIND!r}")
    regs = doc.get("registers")
    if not isinstance(regs, dict):
        errors.append("registers must be an object")
        return errors
    for name, reg in regs.items():
        if not isinstance(reg, dict) or \
                reg.get("kind") not in REGISTER_KINDS:
            errors.append(f"register {name!r}: kind must be "
                          f"one of {REGISTER_KINDS}")
            continue
        entries = reg.get("entries")
        if not isinstance(entries, dict):
            errors.append(f"register {name!r}: entries must "
                          "be an object")
            continue
        for key, e in entries.items():
            if reg["kind"] == "lww-map":
                if not isinstance(e, dict) or \
                        not isinstance(e.get("clock"), int) or \
                        not isinstance(e.get("actor"), str) or \
                        not isinstance(e.get("deleted"), bool) or \
                        "value" not in e:
                    errors.append(
                        f"register {name!r} key {key!r}: entry "
                        "must carry value, int clock, actor "
                        "and bool deleted")
            else:
                for side in ("members", "removed"):
                    stamps = e.get(side) if isinstance(e, dict) \
                        else None
                    if not isinstance(stamps, dict) or \
                            not isinstance(stamps.get("clock"), int) or \
                            not isinstance(stamps.get("actor"), str):
                        errors.append(
                            f"register {name!r} member {key!r}: "
                            f"{side} stamp must carry int clock "
                            "and actor")
    return errors


def _stamp(entry):
    return (entry["clock"], entry["actor"])


# ------------------------------------------------------------ operations

def apply_op(doc, op):
    """A NEW document with one operation applied. An
    operation lands only when its stamp beats the current
    entry's stamp (lww-map), or is recorded as the newest
    stamp for its side (add-wins-set); a stale operation is
    a no-op, which is what makes re-delivery and reordering
    safe. Raises ValueError on a malformed operation."""
    out = copy.deepcopy(doc)
    regs = out.setdefault("registers", {})
    name = op.get("register")
    kind_of_op = op.get("op")
    if not name or not isinstance(op.get("clock"), int) \
            or not op.get("actor"):
        raise ValueError(f"malformed operation: {op!r}")
    stamp = {"clock": op["clock"], "actor": op["actor"]}
    if kind_of_op in ("set", "delete"):
        reg = regs.setdefault(name, {"kind": "lww-map",
                                     "entries": {}})
        if reg["kind"] != "lww-map":
            raise ValueError(f"register {name!r} is not an "
                             "lww-map")
        key = op.get("key")
        if key is None:
            raise ValueError(f"malformed operation: {op!r}")
        cur = reg["entries"].get(key)
        if cur is None or (op["clock"], op["actor"]) > _stamp(cur):
            reg["entries"][key] = {
                "value": op.get("value"),
                "clock": op["clock"], "actor": op["actor"],
                "deleted": kind_of_op == "delete"}
        return out
    if kind_of_op in ("add", "remove"):
        reg = regs.setdefault(name, {"kind": "add-wins-set",
                                     "entries": {}})
        if reg["kind"] != "add-wins-set":
            raise ValueError(f"register {name!r} is not an "
                             "add-wins-set")
        member = op.get("member")
        if member is None:
            raise ValueError(f"malformed operation: {op!r}")
        entry = reg["entries"].setdefault(
            member, {"members": {"clock": -1, "actor": ""},
                     "removed": {"clock": -1, "actor": ""}})
        side = "members" if kind_of_op == "add" else "removed"
        cur = (entry[side]["clock"], entry[side]["actor"])
        if (op["clock"], op["actor"]) > cur:
            entry[side] = stamp
        return out
    raise ValueError(f"unknown op {kind_of_op!r}")


def apply_ops(doc, ops):
    """Fold an offline draft (a list of operations) into a
    document, in list order; convergence does not depend on
    the order (see merge)."""
    out = doc
    for op in ops:
        out = apply_op(out, op)
    return out


# ------------------------------------------------------------ merge

def _merge_lww(a, b):
    entries = {}
    for key in sorted(set(a) | set(b)):
        if key in a and key in b:
            entries[key] = copy.deepcopy(
                a[key] if _stamp(a[key]) >= _stamp(b[key])
                else b[key])
        elif key in a:
            entries[key] = copy.deepcopy(a[key])
        else:
            entries[key] = copy.deepcopy(b[key])
    return {"kind": "lww-map", "entries": entries}


def _merge_set(a, b):
    entries = {}
    for member in sorted(set(a) | set(b)):
        merged = {}
        for side in ("members", "removed"):
            stamps = [e[side] for e in (a.get(member),
                                         b.get(member)) if e]
            best = max(stamps, key=lambda s: (s["clock"],
                                              s["actor"]))
            merged[side] = copy.deepcopy(best)
        entries[member] = merged
    return {"kind": "add-wins-set", "entries": entries}


def merge(a, b):
    """Merge two documents into a NEW document. Commutative,
    associative and idempotent by construction: every choice
    is the maximum under the same total stamp order.
    Raises ValueError when the two documents give one
    register different kinds."""
    errors = validate_document(a) + validate_document(b)
    if errors:
        raise ValueError("; ".join(errors))
    out = new_document()
    names = sorted(set(a["registers"]) | set(b["registers"]))
    for name in names:
        ra, rb = a["registers"].get(name), b["registers"].get(name)
        if ra and rb and ra["kind"] != rb["kind"]:
            raise ValueError(f"register {name!r}: kind "
                             f"conflict {ra['kind']} vs "
                             f"{rb['kind']}")
        reg = ra or rb
        if ra and rb:
            out["registers"][name] = (
                _merge_lww(ra["entries"], rb["entries"])
                if reg["kind"] == "lww-map"
                else _merge_set(ra["entries"], rb["entries"]))
        else:
            out["registers"][name] = copy.deepcopy(reg)
    return out


# ------------------------------------------------------------ views

def live_entries(doc, register):
    """The readable state of one register: for an lww-map,
    {key: value} over non-tombstoned keys; for an
    add-wins-set, the sorted list of present members (a
    member is present when its add stamp beats or ties its
    remove stamp — add-wins)."""
    reg = doc["registers"][register]
    if reg["kind"] == "lww-map":
        return {k: e["value"] for k, e in
                sorted(reg["entries"].items())
                if not e["deleted"]}
    present = []
    for member, e in sorted(reg["entries"].items()):
        add = (e["members"]["clock"], e["members"]["actor"])
        rem = (e["removed"]["clock"], e["removed"]["actor"])
        if add >= rem and e["members"]["clock"] >= 0:
            present.append(member)
    return present


def demo_document_pair():
    """The deterministic worked example behind `demo`: one
    base register and two offline drafts of it, made by two
    actors with no contact — including a concurrent edit of
    one key, a delete racing an older set, and an add/remove
    race on a set member."""
    base = apply_ops(new_document(), [
        {"op": "set", "register": "reading-list",
         "key": "paper-a", "value": "queued",
         "clock": 1, "actor": "base"},
        {"op": "add", "register": "tags", "member": "lod",
         "clock": 1, "actor": "base"},
    ])
    draft_a = [
        {"op": "set", "register": "reading-list",
         "key": "paper-a", "value": "read",
         "clock": 2, "actor": "alice"},
        {"op": "set", "register": "reading-list",
         "key": "paper-b", "value": "queued",
         "clock": 3, "actor": "alice"},
        {"op": "add", "register": "tags", "member": "quality",
         "clock": 2, "actor": "alice"},
    ]
    draft_b = [
        {"op": "set", "register": "reading-list",
         "key": "paper-a", "value": "skimmed",
         "clock": 2, "actor": "bob"},
        {"op": "delete", "register": "reading-list",
         "key": "paper-b", "clock": 4, "actor": "bob"},
        {"op": "remove", "register": "tags", "member": "lod",
         "clock": 2, "actor": "bob"},
        {"op": "add", "register": "tags", "member": "lod",
         "clock": 2, "actor": "bob"},
    ]
    return base, draft_a, draft_b


# ------------------------------------------------------------ commands

def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Automerge CRDT pattern for small "
                    "structured registers (pattern machinery "
                    "only; the wiki's write topology is not "
                    "changed).")
    sub = ap.add_subparsers(dest="command")
    pc = sub.add_parser("check"); pc.add_argument("doc")
    pm = sub.add_parser("merge")
    pm.add_argument("a"); pm.add_argument("b")
    pm.add_argument("--out", default=None)
    pa = sub.add_parser("apply")
    pa.add_argument("doc"); pa.add_argument("ops")
    pa.add_argument("--out", default=None)
    sub.add_parser("demo")
    args = ap.parse_args(argv)
    cmd = args.command or "demo"
    try:
        if cmd == "check":
            doc = _load_json(args.doc)
            errs = validate_document(doc)
            for e in errs:
                print(f"crdt-pattern: {e}", file=sys.stderr)
            print(f"crdt-pattern: document "
                  f"{'INVALID' if errs else 'valid'} "
                  f"({len(doc.get('registers') or {})} "
                  f"register(s))")
            return 1 if errs else 0
        if cmd == "merge":
            merged = merge(_load_json(args.a), _load_json(args.b))
            text = json.dumps(merged, indent=2,
                              ensure_ascii=False) + "\n"
        elif cmd == "apply":
            ops_doc = _load_json(args.ops)
            ops = ops_doc.get("ops") if isinstance(ops_doc, dict) \
                else ops_doc
            if not isinstance(ops, list):
                print("crdt-pattern: ops file must be a list "
                      "or {\"ops\": [...]}", file=sys.stderr)
                return 2
            merged = apply_ops(_load_json(args.doc), ops)
            text = json.dumps(merged, indent=2,
                              ensure_ascii=False) + "\n"
        else:  # demo
            base, draft_a, draft_b = demo_document_pair()
            merged = merge(apply_ops(base, draft_a),
                           apply_ops(base, draft_b))
            payload = {
                "pattern": "automerge-crdt-pattern-half",
                "boundary": "Pattern machinery only: the "
                            "wiki's write topology is NOT "
                            "changed; no multi-master writes "
                            "against wiki content.",
                "merged_document": merged,
                "reading-list_live": live_entries(
                    merged, "reading-list"),
                "tags_live": live_entries(merged, "tags"),
            }
            text = json.dumps(payload, indent=2,
                              ensure_ascii=False) + "\n"
            sys.stdout.write(text)
            return 0
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"crdt-pattern: {e}", file=sys.stderr)
        return 2
    if getattr(args, "out", None):
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"crdt-pattern: wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
