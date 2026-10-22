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

Dedupe (W1.9, scripts/wiki_dedupe.py — the shared design):
an add whose body shares a semantic fingerprint with an
existing item's body is the SAME capture arriving again.
An exact duplicate (or one poorer in commentary) creates
no new item: the existing item is returned flagged
`duplicate`, and the decision is logged to
dedupe-log.jsonl beside the register. A comment-bearing
re-send SUPERSEDES the bare item file — backup first, to
dedupe-backups/ beside the register, the item keeping its
id and state — and a collision (both annotated, differently)
keeps both items. Nothing is dropped silently: every
dedupe outcome is in the log with its survivor named.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import wiki_dedupe  # W1.9 shared dedupe design

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


def _dedupe_log(staging, record):
    wiki_dedupe.log_decision(
        staging, record,
        log_path=Path(staging) / "dedupe-log.jsonl")


def add_item(staging, title, body, at="", by="mehmed"):
    data = load_register(staging)
    items_dir = Path(staging) / "items"
    # W1.9 dedupe: text-as-identity over the bodies already
    # in the inbox — the same capture admitted twice is one
    # item, decided by the shared rules, never silently.
    collision = None
    if items_dir.is_dir():
        for item in data["items"]:
            ipath = items_dir / f"{item['id']}.md"
            if not ipath.is_file():
                continue
            existing_body = wiki_dedupe.strip_frontmatter(
                ipath.read_text(encoding="utf-8"))
            verdict = wiki_dedupe.decide(existing_body, body)
            if verdict["outcome"] == "distinct":
                continue
            if verdict["outcome"] in ("exact-duplicate",
                                       "existing-wins"):
                _dedupe_log(staging, {
                    "door": "staging-inbox",
                    "outcome": verdict["outcome"],
                    "action": "duplicate-kept-existing",
                    "survivor": item["id"],
                    "incoming": "add %r" % title,
                    "fingerprint": verdict["fingerprint"],
                    "backup": None, "at": at or None})
                return {**item, "duplicate": True,
                        "dedupe": verdict["outcome"]}
            if verdict["outcome"] == "incoming-wins":
                backup = wiki_dedupe.backup_before_rewrite(
                    staging, ipath, door="staging-inbox",
                    backup_dir=Path(staging) / "dedupe-backups")
                ipath.write_text(
                    f"---\ntitle: \"{item['title']}\"\n"
                    f"state: {item['state']}\n---\n\n{body}\n",
                    encoding="utf-8")
                _dedupe_log(staging, {
                    "door": "staging-inbox",
                    "outcome": "incoming-wins",
                    "action": "superseded",
                    "survivor": item["id"],
                    "incoming": "add %r" % title,
                    "fingerprint": verdict["fingerprint"],
                    "backup": backup, "at": at or None})
                return {**item, "dedupe": "incoming-wins",
                        "backup": backup}
            collision = (item, verdict)  # keep both; log after
    base = slugify(title)
    existing = {i["id"] for i in data["items"]}
    ident, n = base, 2
    while ident in existing:
        ident = f"{base}-{n}"
        n += 1
    items_dir.mkdir(parents=True, exist_ok=True)
    (items_dir / f"{ident}.md").write_text(
        f"---\ntitle: \"{title}\"\nstate: new\n---\n\n{body}\n",
        encoding="utf-8")
    item = {"id": ident, "title": title, "state": "new", "added": at,
            "history": [{"state": "new", "at": at, "by": by}]}
    data["items"].append(item)
    save_register(staging, data)
    if collision is not None:
        other, verdict = collision
        _dedupe_log(staging, {
            "door": "staging-inbox",
            "outcome": "collision-keep-both",
            "action": "collision-kept-both",
            "survivor": "both: %s + %s" % (other["id"], ident),
            "incoming": "add %r" % title,
            "fingerprint": verdict["fingerprint"],
            "backup": None, "at": at or None})
        return {**item, "dedupe": "collision-keep-both"}
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
