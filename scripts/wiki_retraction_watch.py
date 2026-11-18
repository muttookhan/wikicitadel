#!/usr/bin/env python3
"""Retraction watch over identified sources.

Item: "retraction watch over identified sources" from the
standing Tier A queue (Marathon Round 2 record).

A compiled wiki rests on sources that can later be
retracted, corrected, or withdrawn by their publishers —
and nothing in the corpus notices. This tool keeps a
REGISTER of watched sources, each identified by the id our
own record knows it by (its source-page stem / repo path)
plus its publisher URL, and a recorded retraction status:

  evaluation/retraction-watch.jsonl — one JSON object per
  line, maintained by hand or by the `record` command:

    {"source": "wiki/sources/<stem>.md",   our id for it
     "url": "https://publisher.example/item",  (optional)
     "status": "not-retracted",   not-retracted | corrected |
                                  retracted | withdrawn |
                                  expression-of-concern | unknown
     "checked": "YYYY-MM-DD",     when status was last set
     "note": "..."}               the evidence for the status

Two modes:

  check (default, offline, always available): fold the
  register (a later line for the same source supersedes an
  earlier one — the register is a record, never rewritten),
  flag every watched source whose status is a retraction-
  class status (retracted / withdrawn / corrected /
  expression-of-concern), flag stale entries whose last
  check is older than --stale-days, flag malformed lines,
  and — when compiled pages cite a watched source under
  its id — name the pages resting on a retracted source.
  This mode makes NO network calls, ever.

  fetch (explicit, off by default): for each watched source
  carrying a URL, fetch the page through an INJECTABLE
  fetcher and look for retraction markers in the returned
  text (the publisher's own notices: "retracted",
  "withdrawn", "expression of concern", a corrections
  banner). A marker that disagrees with the recorded
  status is a CHANGE candidate for a human to rule on —
  the tool never edits the register from a fetch. The
  built-in fetcher is DISABLED: fetch mode refuses to run
  unless a fetcher is supplied (library callers pass
  fetch=callable; the CLI has no network path at all in
  this build — wiring a live fetcher is a separate,
  owner-visible act). Tests drive the seam with fakes.

Exit codes: check 0 = nothing flagged, 1 = flags,
2 = usage error. fetch with no fetcher = 2 with the
reason stated.

Usage:
  python3 scripts/wiki_retraction_watch.py [--root DIR]
      [--register PATH] [--stale-days N] [--as-of DATE]
      [--json]
  python3 scripts/wiki_retraction_watch.py record
      --source ID --status STATUS [--url URL] [--note TEXT]

Stdlib only.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/retraction-watch.jsonl"
STATUSES = ("not-retracted", "corrected", "retracted",
            "withdrawn", "expression-of-concern", "unknown")
FLAGGED_STATUSES = ("corrected", "retracted", "withdrawn",
                    "expression-of-concern")
DEFAULT_STALE_DAYS = 180
MARKERS = (
    ("retracted", re.compile(r"\bretracted\b", re.I)),
    ("withdrawn", re.compile(r"\bwithdrawn\b", re.I)),
    ("expression-of-concern",
     re.compile(r"expression of concern", re.I)),
    ("corrected", re.compile(r"\bcorrection\b|\bcorrected\b", re.I)),
)
CITE_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def load_register(path):
    """(entries folded by source — later lines win, malformed
    lines collected). Missing register = the honest empty
    state ([], [], False)."""
    path = Path(path)
    if not path.is_file():
        return [], [], False
    folded, order, malformed = {}, [], []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            malformed.append({"line": lineno, "reason": "not JSON"})
            continue
        if isinstance(entry, dict) and entry.get("kind") == "header":
            continue
        if not isinstance(entry, dict) or not entry.get("source"):
            malformed.append({"line": lineno,
                              "reason": "entry carries no source id"})
            continue
        if entry.get("status") not in STATUSES:
            malformed.append({
                "line": lineno,
                "reason": f"status {entry.get('status')!r} not in "
                        f"the vocabulary {list(STATUSES)}"})
            continue
        src = entry["source"]
        if src not in folded:
            order.append(src)
        folded[src] = entry
    return [folded[s] for s in order], malformed, True


def citing_pages(root, source_id):
    """Compiled pages that cite the watched source: a page
    whose frontmatter sources list names it, or whose body
    wikilinks its stem. Deterministic."""
    root = Path(root)
    wiki = root / "wiki"
    hits = []
    if not wiki.is_dir():
        return hits
    stem = Path(str(source_id)).stem
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel in ("wiki/index.md", "wiki/log.md"):
            continue
        if rel == source_id:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if source_id in text or stem in CITE_RE.findall(text):
            hits.append(rel)
    return hits


def check(root, register_path=None, today=None, stale_days=DEFAULT_STALE_DAYS):
    root = Path(root)
    today = today or date.today()
    register_path = Path(register_path) if register_path \
        else root / REGISTER_REL
    entries, malformed, present = load_register(register_path)
    flagged, stale = [], []
    for entry in entries:
        if entry["status"] in FLAGGED_STATUSES:
            flagged.append({
                "source": entry["source"], "status": entry["status"],
                "url": entry.get("url"), "checked": entry.get("checked"),
                "note": entry.get("note", ""),
                "citing_pages": citing_pages(root, entry["source"]),
            })
        checked_raw = str(entry.get("checked") or "")
        try:
            checked = date.fromisoformat(checked_raw[:10])
        except ValueError:
            checked = None
        if checked is None:
            stale.append({"source": entry["source"],
                          "reason": "no parseable checked date"})
        elif (today - checked).days > stale_days:
            stale.append({"source": entry["source"],
                          "checked": checked.isoformat(),
                          "age_days": (today - checked).days})
    flagged.sort(key=lambda f: f["source"])
    stale.sort(key=lambda f: f["source"])
    return {"tool": "wiki_retraction_watch",
            "register": str(register_path),
            "register_present": present,
            "watched": len(entries), "as_of": today.isoformat(),
            "stale_days": stale_days,
            "flagged": flagged, "flagged_count": len(flagged),
            "stale": stale, "stale_count": len(stale),
            "malformed": malformed,
            "malformed_count": len(malformed)}


def detect_markers(text):
    """Retraction-class markers in publisher text: the
    strongest status named (retracted > withdrawn >
    expression-of-concern > corrected), or None."""
    for status, rx in MARKERS:
        if rx.search(text or ""):
            return status
    return None


def fetch_check(root, register_path=None, fetch=None):
    """The injectable-seam mode. `fetch(url) -> text` is
    REQUIRED: with no fetcher the mode refuses (no network
    machinery is built into this tool). Returns change
    candidates: watched sources whose fetched marker status
    disagrees with the recorded status."""
    if fetch is None:
        raise ValueError(
            "fetch mode has no fetcher: the live fetch seam is "
            "off by default and no network fetcher is built in; "
            "pass fetch=<callable url->text> from a caller that "
            "owns the network act")
    entries, _malformed, _present = load_register(
        Path(register_path) if register_path
        else Path(root) / REGISTER_REL)
    candidates = []
    for entry in entries:
        url = entry.get("url")
        if not url:
            continue
        seen = detect_markers(fetch(url))
        recorded = entry["status"]
        if seen is None or seen == recorded:
            continue
        candidates.append({"source": entry["source"], "url": url,
                           "recorded_status": recorded,
                           "fetched_marker": seen})
    candidates.sort(key=lambda c: c["source"])
    return {"tool": "wiki_retraction_watch", "mode": "fetch",
            "candidates": candidates,
            "candidate_count": len(candidates)}


def record(root, register_path, entry, today=None):
    """Append one register line (the register is append-only;
    folding at read time makes the new line govern)."""
    entry = dict(entry)
    entry.setdefault("checked", (today or date.today()).isoformat())
    if entry.get("status") not in STATUSES:
        raise ValueError(f"status must be one of {list(STATUSES)}")
    if not entry.get("source"):
        raise ValueError("a watched source id is required")
    path = Path(register_path) if register_path else Path(root) / REGISTER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def main(argv):
    ap = argparse.ArgumentParser(
        description="Retraction watch over identified sources "
                    "(offline check; the fetch seam is off by default).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--register", default=None)
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    pr = sub.add_parser("record", help="append a register line")
    pr.add_argument("--source", required=True)
    pr.add_argument("--status", required=True, choices=STATUSES)
    pr.add_argument("--url", default=None)
    pr.add_argument("--note", default="")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "record":
        entry = {"source": args.source, "status": args.status,
                 "note": args.note}
        if args.url:
            entry["url"] = args.url
        try:
            written = record(root, args.register, entry)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"recorded: {json.dumps(written, sort_keys=True)}")
        return 0
    today = date.today()
    if args.as_of:
        try:
            today = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"error: --as-of {args.as_of!r} is not an ISO date",
                  file=sys.stderr)
            return 2
    report = check(root, args.register, today=today,
                   stale_days=args.stale_days)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("== Retraction watch ==")
        if not report["register_present"]:
            print("no register yet (evaluation/retraction-watch.jsonl)"
                  " — the honest empty state; nothing is watched")
        print(f"watched: {report['watched']}   flagged:"
              f" {report['flagged_count']}   stale:"
              f" {report['stale_count']}   malformed:"
              f" {report['malformed_count']}")
        for f in report["flagged"]:
            pages = (", ".join(f["citing_pages"])
                     if f["citing_pages"] else "no compiled page cites it")
            print(f"  FLAGGED {f['source']} — {f['status']}"
                  f" (checked {f['checked']}); resting pages: {pages}")
        for s in report["stale"]:
            print(f"  stale {s['source']} — {s.get('reason') or 'last checked ' + str(s.get('checked'))}")
        for m in report["malformed"]:
            print(f"  malformed line {m['line']} — {m['reason']}")
    flagged_any = report["flagged"] or report["stale"] or report["malformed"]
    return 1 if flagged_any else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
