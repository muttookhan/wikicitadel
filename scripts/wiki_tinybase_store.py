#!/usr/bin/env python3
"""TinyBase store pattern half — MergeableStore / listener /
checkpoint patterns for LOCAL single-user TOOL state.

Marathon R12 lane BB (ideas board line 186, Round 10 RB
research, Tier A): the TinyBase store family's patterns,
restated in our own words and implemented with stdlib only.
PATTERN ONLY, stated on its face: this store holds LOCAL,
single-user TOOL state only (a tool's own scratch settings,
cursors and draft flags). It is NOT a wiki content store, NOT
a sync layer and NOT shared state: no wiki page, register or
golden/battery file is ever held here, and nothing here is
wired into any gate, the sweep or the Ask door.

The patterns:
  - MergeableStore: tables -> rows -> cells, each cell carrying
    {value, counter, actor}; merging two stores keeps, per cell,
    the entry with the greater (counter, actor) stamp — the
    same LWW rule family as scripts/wiki_loro_merge.py, applied
    to tool state instead of outline state.
  - Listeners: a callable registered with add_listener is
    notified, in registration order, of every set/delete/merge
    change with a plain change dict. A listener that raises does
    not break the store: the failure is recorded in
    listener_errors and notification continues.
  - Checkpoints: checkpoint(label) snapshots the whole store
    content under an id with its sha256; rollback(id) restores
    that exact content; checkpoints survive save/load.

The seed store evaluation/tinybase-tool-state.json is EMPTY-
BUT-VALID (no tables): populating it is a tool's own act, not
part of this build. Commands: check / checkpoint / report over
a store JSON file. Exit 0 ok; 1 invalid on check; 2 usage.
Stdlib only, no network.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE_FILE = ROOT / "evaluation" / "tinybase-tool-state.json"


def _stamp(cell):
    return (cell.get("counter", 0), str(cell.get("actor", "")))


def content_hash(tables):
    return hashlib.sha256(json.dumps(tables, sort_keys=True,
                                     ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


class MergeableStore:
    """In-memory mergeable store for local tool state."""

    def __init__(self, tables=None, checkpoints=None):
        self.tables = copy.deepcopy(tables) if tables else {}
        self.checkpoints = copy.deepcopy(checkpoints) if checkpoints else {}
        self.listeners = []
        self.listener_errors = []

    # -- cells -------------------------------------------------
    def set_cell(self, table, row, cell, value, counter, actor):
        cur = self.tables.setdefault(table, {}).setdefault(row, {})
        new = {"value": value, "counter": counter, "actor": actor}
        old = cur.get(cell)
        if old is not None and _stamp(old) > _stamp(new):
            return False  # a newer stamp already holds this cell
        cur[cell] = new
        self._notify({"op": "set", "table": table, "row": row,
                      "cell": cell, "value": value})
        return True

    def get_cell(self, table, row, cell, default=None):
        c = self.tables.get(table, {}).get(row, {}).get(cell)
        return c["value"] if c else default

    def delete_row(self, table, row):
        if row in self.tables.get(table, {}):
            del self.tables[table][row]
            self._notify({"op": "delete-row", "table": table, "row": row})
            return True
        return False

    def table_values(self, table):
        """Plain {row: {cell: value}} view of one table."""
        return {r: {c: cell["value"] for c, cell in sorted(cells.items())}
                for r, cells in sorted(self.tables.get(table, {}).items())}

    # -- merge -------------------------------------------------
    def merge(self, other):
        """Merge another MergeableStore (or raw tables dict) in;
        per cell the greater (counter, actor) stamp wins.
        Returns the number of cells changed."""
        tables = other.tables if isinstance(other, MergeableStore) else other
        changed = 0
        for t, rows in (tables or {}).items():
            for r, cells in rows.items():
                for c, cell in cells.items():
                    cur = self.tables.get(t, {}).get(r, {}).get(c)
                    if cur is None or _stamp(cell) > _stamp(cur):
                        self.tables.setdefault(t, {}).setdefault(r, {})[c] \
                            = copy.deepcopy(cell)
                        changed += 1
        if changed:
            self._notify({"op": "merge", "cells_changed": changed})
        return changed

    # -- listeners ---------------------------------------------
    def add_listener(self, fn):
        self.listeners.append(fn)
        return fn

    def _notify(self, change):
        for fn in list(self.listeners):
            try:
                fn(change)
            except Exception as e:  # a listener never breaks the store
                self.listener_errors.append(
                    {"change": change, "error": f"{type(e).__name__}: {e}"})

    # -- checkpoints -------------------------------------------
    def checkpoint(self, label=""):
        cid = f"cp-{len(self.checkpoints) + 1:04d}"
        while cid in self.checkpoints:
            cid = cid + "x"
        self.checkpoints[cid] = {
            "label": label, "hash": content_hash(self.tables),
            "tables": copy.deepcopy(self.tables)}
        self._notify({"op": "checkpoint", "checkpoint": cid,
                      "label": label})
        return cid

    def rollback(self, checkpoint_id):
        cp = self.checkpoints.get(checkpoint_id)
        if cp is None:
            return False
        if content_hash(cp["tables"]) != cp["hash"]:
            return False  # checkpoint content no longer matches its hash
        self.tables = copy.deepcopy(cp["tables"])
        self._notify({"op": "rollback", "checkpoint": checkpoint_id})
        return True

    # -- persistence -------------------------------------------
    def to_dict(self):
        return {"kind": "tinybase-tool-state", "pattern_only": True,
                "scope": "local single-user tool state only",
                "tables": self.tables, "checkpoints": self.checkpoints}

    @classmethod
    def from_dict(cls, obj):
        return cls(obj.get("tables"), obj.get("checkpoints"))

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2,
                                         sort_keys=True,
                                         ensure_ascii=False) + "\n",
                              encoding="utf-8")

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(
            encoding="utf-8")))


def load_store_file(path=None):
    p = Path(path) if path else STORE_FILE
    if not p.is_file():
        return None, [f"store file missing: {p}"]
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, [f"store file is not valid JSON ({e})"]
    errors = []
    if obj.get("kind") != "tinybase-tool-state":
        errors.append("kind must be 'tinybase-tool-state'")
    if obj.get("pattern_only") is not True:
        errors.append("pattern_only must be true (stated on its face)")
    if not isinstance(obj.get("tables"), dict):
        errors.append("tables must be a dict")
    for cid, cp in (obj.get("checkpoints") or {}).items():
        if not isinstance(cp, dict) or content_hash(cp.get("tables") or {}) \
                != cp.get("hash"):
            errors.append(f"checkpoint {cid}: stored hash does not match "
                          "its tables")
    for t, rows in (obj.get("tables") or {}).items():
        for r, cells in rows.items():
            for c, cell in cells.items():
                if not isinstance(cell, dict) or "value" not in cell \
                        or not isinstance(cell.get("counter"), int) \
                        or not cell.get("actor"):
                    errors.append(f"{t}/{r}/{c}: cell must carry value, "
                                  "integer counter and actor")
    return obj, errors


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="TinyBase store pattern half (pattern only).")
    sub = ap.add_subparsers(dest="command")
    for name in ("check", "report", "checkpoint"):
        sp = sub.add_parser(name); sp.add_argument("--store", default=None)
        if name == "checkpoint":
            sp.add_argument("--label", default="")
    args = ap.parse_args(argv)
    cmd = args.command or "report"
    if cmd == "check":
        _o, errors = load_store_file(args.store)
        for e in errors:
            print(f"tinybase-store: {e}", file=sys.stderr)
        print(f"tinybase-store: store {'INVALID' if errors else 'valid'} "
              "(pattern only; local tool state only)")
        return 1 if errors else 0
    obj, errors = load_store_file(args.store)
    if errors:
        for e in errors:
            print(f"tinybase-store: {e}", file=sys.stderr)
        return 1
    store = MergeableStore.from_dict(obj)
    if cmd == "checkpoint":
        cid = store.checkpoint(args.label)
        store.save(Path(args.store) if args.store else STORE_FILE)
        print(f"tinybase-store: checkpoint {cid} "
              f"(hash {store.checkpoints[cid]['hash'][:16]}...)")
        return 0
    tables = store.tables
    cells = sum(len(cells) for rows in tables.values()
                for cells in rows.values())
    print(f"tinybase-store: {len(tables)} table(s), {cells} cell(s), "
          f"{len(store.checkpoints)} checkpoint(s); content hash "
          f"{content_hash(tables)[:16]}... (local tool state only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
