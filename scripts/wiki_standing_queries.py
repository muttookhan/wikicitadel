#!/usr/bin/env python3
"""Standing queries — the filing path (WikiCitadel v1;
saved failed searches).

The register is evaluation/standing-queries.jsonl in the wiki
repo: one JSON object per standing query (shape documented in
tools/lens/lenslib.py, which reads it at Lens build time). The
Lens itself is read-only, so a watch is FILED, never saved by the
page: the owner asks (in chat, or through the Ask door from a
zero-results page), and the agent files it here. Every Lens build
then re-runs each query and the Briefing reports what is new
since the query's last-looked stamp; the stamp advances only in
a build that reports the query (see lenslib).

Usage:
  python3 scripts/wiki_standing_queries.py add --name NAME --query Q
          [--from zero-results|manual|...]
  python3 scripts/wiki_standing_queries.py list
  python3 scripts/wiki_standing_queries.py pause  sq-0001
  python3 scripts/wiki_standing_queries.py resume sq-0001
  python3 scripts/wiki_standing_queries.py remove sq-0001

add refuses an exact duplicate query (case-insensitive) and
prints the existing record instead. Mutations print the record
they wrote. Nothing here re-runs a query — that is the build's
job.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REGISTER_REL = "evaluation/standing-queries.jsonl"


def load(repo: Path) -> list[dict]:
    path = repo / REGISTER_REL
    records = []
    if not path.is_file():
        return records
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("id") and rec.get("query"):
            records.append(rec)
    return records


def write(repo: Path, records: list[dict]) -> None:
    path = repo / REGISTER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True)
             for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""),
                    encoding="utf-8")


def next_id(records: list[dict]) -> str:
    top = 0
    for r in records:
        m = re.fullmatch(r"sq-(\d+)", str(r.get("id") or ""))
        if m:
            top = max(top, int(m.group(1)))
    return f"sq-{top + 1:04d}"


def find(records: list[dict], rid: str) -> dict | None:
    for r in records:
        if r.get("id") == rid:
            return r
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]),
                    help="wiki repo root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="file a new standing query")
    p_add.add_argument("--name", required=True,
                       help="the owner's name for the query")
    p_add.add_argument("--query", required=True, help="the search string")
    p_add.add_argument("--from", dest="saved_from", default="manual",
                       help="where the save came from (default: manual)")
    sub.add_parser("list", help="list the register")
    for verb in ("pause", "resume", "remove"):
        p = sub.add_parser(verb, help=f"{verb} one standing query")
        p.add_argument("id")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    records = load(repo)

    if args.cmd == "list":
        if not records:
            print("No standing queries filed.")
            return 0
        for r in records:
            state = "paused" if r.get("paused") else "watching"
            looked = r.get("last_looked_at") or "not yet looked (no build since filing)"
            print(f"{r['id']}  {r.get('name')!r}  query={r['query']!r}  "
                  f"{state}  last looked: {looked}")
        return 0

    if args.cmd == "add":
        query = args.query.strip()
        if not query:
            print("error: --query is empty", file=sys.stderr)
            return 2
        for r in records:
            if str(r.get("query", "")).strip().lower() == query.lower():
                print(f"already filed: {r['id']} "
                      f"({r.get('name')!r}) — not duplicated")
                return 0
        rec = {"id": next_id(records), "name": args.name.strip(),
               "query": query, "saved_from": args.saved_from,
               "created_at": datetime.now(timezone.utc)
               .isoformat(timespec="seconds"),
               "last_looked_at": None, "last_looked_head": None,
               "seen": {}, "advances": 0}
        records.append(rec)
        write(repo, records)
        print(f"filed {rec['id']}: {json.dumps(rec, ensure_ascii=False, sort_keys=True)}")
        print("The next Lens build sets its baseline; later builds "
              "report what is new since you last looked.")
        return 0

    rec = find(records, args.id)
    if rec is None:
        print(f"error: no standing query {args.id}", file=sys.stderr)
        return 2
    if args.cmd == "pause":
        rec["paused"] = True
    elif args.cmd == "resume":
        rec.pop("paused", None)
    elif args.cmd == "remove":
        records = [r for r in records if r.get("id") != args.id]
        write(repo, records)
        print(f"removed {args.id} ({rec.get('name')!r})")
        return 0
    write(repo, records)
    print(f"{args.cmd}d {args.id}: {json.dumps(rec, ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
