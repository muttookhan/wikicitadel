#!/usr/bin/env python3
"""wiki_staging_inbox.py — staging inbox for captures (Marathon R3,
Tier B bundle "Graph, portal and capture forms", row 9).

Patterns: the staging-inbox shapes of Karakeep / Linkwarden /
Readeck / Paperless-ngx (AGPL/GPL — IDEAS ONLY; re-implemented
from the shape). Captures land in a STAGING inbox first and only
leave it through a reviewed state move — nothing files itself.

Layout (all in the files, never a database):

    <staging-dir>/                 default <root>/staging/inbox
        register.json              the sidecar register: the states
        items/<id>.md              the captured item itself

Register format: {"items": [{"id", "title", "state", "added",
"history": [{"state", "at", "by"}]}]}. States:

    new -> triaged -> filed
    new -> parked ; triaged -> parked ; parked -> triaged (revive)

Any other transition is refused with the allowed moves named.
`list` prints items (optionally one --state); `move` performs one
reviewed transition and appends to the item's history in the
register. The item file itself is never edited by a move.

CLI: --root defaults to the tree root; --staging-dir overrides.
Exit 0 ok, 1 refused transition, 2 missing input.
"""
import argparse
import json
import re
import sys
from pathlib import Path

STATES = ("new", "triaged", "filed", "parked")
TRANSITIONS = {
    "new": {"triaged", "parked"},
    "triaged": {"filed", "parked"},
    "parked": {"triaged"},
    "filed": set(),
}


def load_register(staging):
    reg = Path(staging) / "register.json"
    if reg.exists():
        return json.loads(reg.read_text(encoding="utf-8"))
    return {"items": []}


def save_register(staging, data):
    Path(staging).mkdir(parents=True, exist_ok=True)
    (Path(staging) / "register.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "item"


def add_item(staging, title, body, at="", by="mehmed"):
    data = load_register(staging)
    base = slugify(title)
    existing = {i["id"] for i in data["items"]}
    ident, n = base, 2
    while ident in existing:
        ident = f"{base}-{n}"
        n += 1
    items_dir = Path(staging) / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    (items_dir / f"{ident}.md").write_text(
        f"---\ntitle: \"{title}\"\nstate: new\n---\n\n{body}\n",
        encoding="utf-8")
    item = {"id": ident, "title": title, "state": "new", "added": at,
            "history": [{"state": "new", "at": at, "by": by}]}
    data["items"].append(item)
    save_register(staging, data)
    return item


def move(staging, ident, to_state, at="", by="mehmed"):
    data = load_register(staging)
    for item in data["items"]:
        if item["id"] == ident:
            cur = item["state"]
            if to_state not in TRANSITIONS.get(cur, set()):
                allowed = sorted(TRANSITIONS.get(cur, set()))
                raise ValueError(
                    f"refused: {cur} -> {to_state} is not an allowed "
                    f"transition (allowed from {cur}: "
                    f"{', '.join(allowed) or 'none — filed is final'})")
            item["state"] = to_state
            item["history"].append({"state": to_state, "at": at, "by": by})
            save_register(staging, data)
            return item
    raise KeyError(f"no such item: {ident}")


def list_items(staging, state=None):
    data = load_register(staging)
    return [i for i in data["items"]
            if state is None or i["state"] == state]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--staging-dir", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--body", default="")
    a.add_argument("--at", default="")
    li = sub.add_parser("list")
    li.add_argument("--state", choices=STATES, default=None)
    mv = sub.add_parser("move")
    mv.add_argument("id")
    mv.add_argument("to_state", choices=STATES)
    mv.add_argument("--at", default="")
    ns = ap.parse_args(argv)
    staging = Path(ns.staging_dir) if ns.staging_dir else \
        Path(ns.root) / "staging" / "inbox"
    if ns.cmd == "add":
        print(json.dumps(add_item(staging, ns.title, ns.body, ns.at),
                         indent=2))
        return 0
    if ns.cmd == "list":
        print(json.dumps(list_items(staging, ns.state), indent=2))
        return 0
    try:
        print(json.dumps(move(staging, ns.id, ns.to_state, ns.at),
                         indent=2))
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
