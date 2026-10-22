#!/usr/bin/env python3
"""Memento TimeMap over page history (Round-7 research
candidates; built 2026-10-22, board sweep).

RFC 7089 (Memento) gives web archives a standard shape: for
an original resource (URI-R), a TimeMap (URI-L) lists every
Memento (URI-M) with its datetime, and a TimeGate (URI-G)
negotiates to the memento nearest a requested datetime.
This wiki's archive IS its git history — every committed
revision of a page is a memento, datetimes are the commit
times, and the retention policy's recall already treats
git as the point-in-time store. This tool renders that
history in the Memento shape:

  timemap <page> [--format link|json]
    The page's TimeMap: original (the page path), a
    self-describing timegate (this tool with --at), and one
    memento per commit that touched the page, newest first,
    each with its commit, its commit datetime (HTTP-date),
    and the retrieval route (git show <commit>:<page>).
  at <page> <YYYY-MM-DD[THH:MM:SS]>
    The timegate answer: the newest memento at or before
    the requested datetime — the revision that stood at
    that moment — or a named no-memento answer when the
    page did not yet exist.

Read-only over git: nothing is checked out, written into
the tree, or restored; a memento is retrieved by the
reader with the stated git command. Datetimes are the
COMMIT datetimes from git's own record (author date), the
same evidence the retention recall uses. A page with no
commits is a named answer, not an empty map.

Stdlib only.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True,
                          check=True).stdout


def page_history(rel_path):
    """[(commit, datetime)] newest first, from git's own
    record; [] when the path has no commits."""
    out = _git("log", "--follow", "--format=%H %aI", "--",
               rel_path)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        commit, iso = line.split(" ", 1)
        rows.append((commit,
                     datetime.fromisoformat(iso)))
    return rows


def timemap(rel_path):
    hist = page_history(rel_path)
    return {
        "original": rel_path,
        "timegate": {"tool": "scripts/wiki_timemap.py at",
                     "page": rel_path},
        "mementos": [
            {"commit": commit,
             "datetime": dt.astimezone(timezone.utc).strftime(
                 "%Y-%m-%dT%H:%M:%SZ"),
             "http_date": format_datetime(
                 dt.astimezone(timezone.utc), usegmt=True),
             "retrieve": f"git show {commit}:{rel_path}"}
            for commit, dt in hist],
    }


def render_link(rel_path):
    """The RFC 7089 link-format serialisation."""
    tm = timemap(rel_path)
    base = f"<{rel_path}>"
    lines = [f"{base}; rel=\"original\""]
    lines.append(f"<timemap:{rel_path}>; rel=\"self\"; "
                 f"type=\"application/link-format\"")
    lines.append(f"<timegate:{rel_path}>; rel=\"timegate\"")
    for m in tm["mementos"]:
        lines.append(
            f"<memento:{m['commit']}:{rel_path}>; "
            f"rel=\"memento\"; datetime=\"{m['http_date']}\"")
    return ",\n".join(lines) + "\n"


def at(rel_path, when):
    """The timegate: newest memento at or before `when`."""
    hist = page_history(rel_path)
    for commit, dt in hist:
        if dt <= when:
            return {"page": rel_path,
                    "requested": when.isoformat(),
                    "memento": commit,
                    "datetime": dt.isoformat(),
                    "retrieve": f"git show {commit}:{rel_path}"}
    return {"page": rel_path, "requested": when.isoformat(),
            "memento": None,
            "note": "no memento at or before the requested "
                    "time — the page did not yet exist in "
                    "the record"}


def _parse_when(text):
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"not an ISO datetime: {text!r} "
                         "(use YYYY-MM-DD or "
                         "YYYY-MM-DDTHH:MM:SS, with offset)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Memento TimeMap over a page's git "
                    "history (RFC 7089 shape).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("timemap")
    t.add_argument("page")
    t.add_argument("--format", choices=["link", "json"],
                   default="link")
    g = sub.add_parser("at")
    g.add_argument("page")
    g.add_argument("when")
    a = ap.parse_args(argv)
    if a.cmd == "timemap":
        if not page_history(a.page):
            print(f"no mementos: {a.page} has no commits in "
                  "this tree's record")
            return 1
        if a.format == "json":
            print(json.dumps(timemap(a.page), indent=2))
        else:
            print(render_link(a.page), end="")
        return 0
    if a.cmd == "at":
        ans = at(a.page, _parse_when(a.when))
        print(json.dumps(ans, indent=2))
        return 0 if ans["memento"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
