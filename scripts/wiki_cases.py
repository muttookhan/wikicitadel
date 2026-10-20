#!/usr/bin/env python3
"""Contradiction Cases + the owner's adjudication queue.

WikiCitadel v1; two patterns from the feature survey
(docs/research-notes.md):

  * Contradiction Cases (Agent-Memory-Hub): a
    contradiction becomes a CASE with a lifecycle — opened with
    both claims cited, listed by status, closed by the owner's
    ruling, the record kept forever. A Case is not a callout
    that rots in a page margin.
  * Adjudication queue (Magnemo): the owner's pending
    decisions assembled into ONE queue, oldest first. The queue
    PREPARES decisions; it never makes them. Items are decided
    one at a time, in writing, in chat, by the owner.

TIME-AWARE CLASSIFICATION (the design warning from the
survey): a naive contradiction pass over
5,420 memories elsewhere produced 99.7% false positives, nearly
all same-fact-different-time. So a Case opens ONLY when two
claims about the same fact cannot both be true AT THE SAME
as-of time:

  * claim B missing entirely     -> no-opposing-claim
    (a multiply-supported statement is evidence FOR a claim,
    not a contradiction — this is what the observations pass
    and lint Lane 1 actually produce today)
  * different fact slugs          -> different-fact
  * either as_of missing          -> indeterminate (no Case:
    a conflict that cannot be placed in time cannot be judged)
  * same fact, as_of dates differ -> supersession (the newer
    statement supersedes the older; recorded, never a Case)
  * same fact, same as_of         -> contradiction (a Case
    opens; the owner rules)

The classifier judges TIME and identity of fact. Whether two
texts actually oppose each other is asserted by whoever opens
the candidate (a lint finding or a human); the classifier
decides whether that asserted conflict is a contradiction at
one point in time, a supersession across time, or not a
conflict at all.

The register is evaluation/contradiction-cases.jsonl: a header
line (the decisions-register convention), then append-only
JSON lines — {"kind": "case", ...} openings and
{"kind": "ruling", ...} rulings. A Case's current state is
the fold of its lines; nothing is ever rewritten or deleted.

Commands:
  open    classify a candidate pair and record it; only a
          same-time contradiction becomes an open Case
  list    show Cases by status (default: open; --all for the
          full register including closed records and rulings)
  rule    record the owner's ruling on an open Case
          (append-only; the Case closes, the record stays)
  queue   assemble the adjudication queue from staged gateway
          proposals (read-only), [[ideas]] Waiting items,
          open Cases and open talk-page disputes, oldest
          first, and file it at
          wiki/filings/adjudication-queue-<date>.md

Stdlib only.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "contradiction-cases.jsonl"
IDEAS = ROOT / "wiki" / "ideas.md"
STAGING = ROOT / "staging" / "proposed"
TALK = ROOT / "wiki" / "talk"
FILINGS = ROOT / "wiki" / "filings"

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

REGISTER_HEADER = {
    "kind": "header",
    "register": "contradiction-cases",
    "version": 1,
    "created": "WikiCitadel v1",
    "purpose": ("Contradiction Cases for the LLM Wiki (WikiCitadel v1; "
                "pattern: Agent-Memory-Hub contradiction Cases, "
                "the feature survey). A Case opens only "
                "when two claims about the same fact cannot both "
                "be true at the same as-of time; a newer claim "
                "superseding an older one is a supersession, "
                "recorded as such, never a Case. Cases are closed "
                "only by the owner's ruling, recorded here; the "
                "record is append-only and never deleted."),
    "maintenance": ("Maintained with scripts/wiki_cases.py: "
                    "`open` classifies and records a candidate, "
                    "`rule` appends the owner's ruling. Where "
                    "this register and wiki/log.md disagree, the "
                    "human record governs."),
}


# -- register I/O -----------------------------------------------------------

def read_register(path=REGISTER):
    """Return (cases, rulings): case_id -> opening entry, and
    case_id -> latest ruling entry. Missing file = empty."""
    cases, rulings = {}, {}
    if not path.is_file():
        return cases, rulings
    for line in path.read_text(encoding="utf-8",
                               errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("kind") == "case":
            cases[entry["case_id"]] = entry
        elif entry.get("kind") == "ruling":
            rulings[entry["case_id"]] = entry
    return cases, rulings


def case_status(entry, rulings):
    """Folded status of one Case: its opening status, replaced
    by closed-ruled once a ruling line exists."""
    if entry["case_id"] in rulings:
        return "closed-ruled"
    return entry["status"]


def open_cases(path=REGISTER):
    cases, rulings = read_register(path)
    return [e for e in cases.values()
            if case_status(e, rulings) == "open"]


def _append(entry, path=REGISTER):
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.is_file() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8") as fh:
        if needs_header:
            fh.write(json.dumps(REGISTER_HEADER) + "\n")
        fh.write(json.dumps(entry) + "\n")


def _next_case_id(path=REGISTER):
    cases, _ = read_register(path)
    n = 0
    for cid in cases:
        m = re.match(r"case-(\d+)$", cid)
        if m:
            n = max(n, int(m.group(1)))
    return f"case-{n + 1:04d}"


# -- time-aware classification ----------------------------------------------

def _parse_date(value):
    if not value:
        return None
    m = DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)),
                    int(m.group(3)))
    except ValueError:
        return None


def classify(claim_a, claim_b):
    """Classify an asserted conflict between two claims about
    (allegedly) one fact. Each claim is a dict with keys:
    fact (slug), page, text, as_of (ISO date or None).
    claim_b may be None. Returns (classification, reason)."""
    if claim_b is None:
        return ("no-opposing-claim",
                "only one claim exists; a statement supported "
                "by several pages is evidence for it, not a "
                "contradiction — a Case needs two claims that "
                "cannot both be true")
    if claim_a.get("fact") != claim_b.get("fact"):
        return ("different-fact",
                "the two claims carry different fact slugs, so "
                "they are not two tellings of one fact")
    da, db = _parse_date(claim_a.get("as_of")), \
        _parse_date(claim_b.get("as_of"))
    if da is None or db is None:
        return ("indeterminate",
                "at least one claim carries no usable as_of "
                "date; a conflict that cannot be placed in time "
                "cannot be judged a contradiction, and no Case "
                "opens on it")
    if da != db:
        newer = "B" if db > da else "A"
        return ("supersession",
                f"same fact, different as-of times ({da} vs "
                f"{db}): claim {newer} is the later statement "
                "and supersedes the earlier one — a "
                "supersession, not a contradiction")
    return ("contradiction",
            f"same fact, same as-of time ({da}): the two "
            "claims cannot both be true at that time — a Case "
            "opens for the owner to rule on")


# -- commands: open / list / rule -------------------------------------------

def cmd_open(args):
    claim_a = {"fact": args.fact, "page": args.page_a,
               "text": args.text_a, "as_of": args.as_of_a}
    claim_b = None
    if args.page_b or args.text_b:
        claim_b = {"fact": args.fact, "page": args.page_b,
                   "text": args.text_b, "as_of": args.as_of_b}
    classification, reason = classify(claim_a, claim_b)
    status = {"contradiction": "open",
              "supersession": "closed-supersession",
              "indeterminate": "indeterminate"}.get(
                  classification, "closed-not-a-case")
    case_id = _next_case_id()
    entry = {
        "kind": "case",
        "case_id": case_id,
        "opened": args.date or date.today().isoformat(),
        "status": status,
        "classification": classification,
        "classification_reason": reason,
        "fact": args.fact,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "source": args.source,
        "note": args.note,
    }
    _append(entry)
    print(f"{case_id}: classification={classification} "
          f"status={status}")
    print(f"  {reason}")
    return 0


def cmd_list(args):
    cases, rulings = read_register()
    shown = 0
    for cid in sorted(cases):
        entry = cases[cid]
        status = case_status(entry, rulings)
        if not args.all and status != args.status:
            continue
        shown += 1
        print(f"{cid} [{status}] {entry['classification']} — "
              f"fact: {entry['fact']} (opened {entry['opened']})")
        print(f"  A: {entry['claim_a']['page']} "
              f"(as of {entry['claim_a'].get('as_of')}): "
              f"{entry['claim_a']['text']}")
        if entry.get("claim_b"):
            print(f"  B: {entry['claim_b']['page']} "
                  f"(as of {entry['claim_b'].get('as_of')}): "
                  f"{entry['claim_b']['text']}")
        if cid in rulings:
            r = rulings[cid]
            print(f"  Ruling ({r['date']}, by {r['ruled_by']}): "
                  f"{r['ruling']}")
    if not shown:
        scope = "all" if args.all else args.status
        print(f"no {scope} Cases on the register")
    return 0


def cmd_rule(args):
    cases, rulings = read_register()
    if args.case not in cases:
        print(f"error: {args.case} is not on the register",
              file=sys.stderr)
        return 2
    if case_status(cases[args.case], rulings) != "open":
        print(f"error: {args.case} is not open "
              f"(status: {case_status(cases[args.case], rulings)})",
              file=sys.stderr)
        return 2
    _append({
        "kind": "ruling",
        "case_id": args.case,
        "date": args.date or date.today().isoformat(),
        "ruled_by": "owner",
        "ruling": args.ruling,
        "winner": args.winner,
    })
    print(f"{args.case}: ruling recorded — Case closed, "
          f"record stays")
    return 0


# -- the adjudication queue ---------------------------------------------------

def queue_proposals():
    """Staged gateway proposals awaiting the owner's review.
    READ-ONLY: this reads staging/proposed/*.json and never
    writes to the gateway or its staging area. A proposal that
    already carries a promotion/authorisation is decided, so
    it does not queue."""
    items = []
    if not STAGING.is_dir():
        return items
    for path in sorted(STAGING.glob("prop-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8",
                                             errors="ignore"))
        except json.JSONDecodeError:
            continue
        if data.get("promoted_at") or data.get("authorisation"):
            continue
        when = _parse_date(data.get("submitted_at")) or \
            date(1970, 1, 1)
        label = (f"Staged gateway proposal {data.get('proposal_id', path.stem)}"
                 f" — target `{data.get('target_path', '?')}`,"
                 f" by {data.get('submitted_by', '?')},"
                 f" state {data.get('state', '?')}")
        items.append({"date": when, "rank": 0, "label": label,
                      "source": f"staging/proposed/{path.name}"})
    return items


def queue_cases():
    items = []
    for entry in open_cases():
        when = _parse_date(entry.get("opened")) or date(1970, 1, 1)
        items.append({
            "date": when, "rank": 1,
            "label": (f"Contradiction Case {entry['case_id']} — "
                      f"{entry['fact']}: {entry['claim_a']['page']}"
                      f" vs {entry['claim_b']['page']}"),
            "source": "evaluation/contradiction-cases.jsonl"})
    return items


def queue_talk():
    """Open talk-page disputes (AGENTS.md: dispute_status:
    open). The wiki/talk/ directory may not exist yet."""
    items = []
    if not TALK.is_dir():
        return items
    for path in sorted(TALK.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"^dispute_status:\s*open\s*$", text,
                         re.MULTILINE):
            continue
        when = _parse_date(text) or date(1970, 1, 1)
        title = re.search(r"^title:\s*\"?(.+?)\"?\s*$", text,
                          re.MULTILINE)
        label = (title.group(1) if title
                 else f"Dispute: {path.stem}")
        items.append({"date": when, "rank": 2, "label": label,
                      "source": f"wiki/talk/{path.name}"})
    return items


def queue_ideas():
    """[[ideas]] Waiting items: bullets under '## Waiting for
    your call' up to the next '## ' heading. The date is the
    last ISO date on the line (the board's convention: idea,
    who suggested it, the date)."""
    items = []
    if not IDEAS.is_file():
        return items
    in_waiting = False
    for line in IDEAS.read_text(encoding="utf-8",
                                errors="ignore").splitlines():
        if line.startswith("## "):
            in_waiting = line.strip() == "## Waiting for your call"
            continue
        if not in_waiting or not line.startswith("- **"):
            continue
        m = re.match(r"- \*\*(.+?)\*\*", line)
        if not m:
            continue
        dates = DATE_RE.findall(line)
        when = None
        if dates:
            y, mo, d = (int(x) for x in dates[-1])
            when = date(y, mo, d)
        items.append({"date": when or date(1970, 1, 1),
                      "rank": 3,
                      "label": f"Idea: {m.group(1)}",
                      "source": "wiki/ideas.md"})
    return items


def build_queue():
    items = (queue_proposals() + queue_cases() + queue_talk()
             + queue_ideas())
    items.sort(key=lambda i: (i["date"], i["rank"], i["label"]))
    return items


def render_queue(items, run_date, counts):
    lines = [
        "---",
        f"title: Adjudication queue — {run_date}",
        "type: query",
        f"created: {run_date}",
        f"updated: {run_date}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [adjudication, queue, decisions, owner, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Adjudication queue — {run_date}",
        "",
        "> [!warning] AWAITING OWNER — the queue prepares"
        " decisions, it never makes them",
        "> Assembled by `scripts/wiki_cases.py queue`"
        " (WikiCitadel v1; Magnemo-style adjudication, from"
        " the feature survey): every decision currently waiting on"
        " the owner, from the places such decisions already"
        " live — staged gateway proposals, the [[ideas]]"
        " Waiting list, open contradiction Cases, open"
        " talk-page disputes — in ONE queue, oldest first."
        " Each item is decided by the owner, one at a time, in"
        " writing, in chat. Nothing here is decided, ranked by"
        " importance, or actioned by appearing here. This"
        " filing feeds the weekly 5-decisions delivery.",
        "",
        (f"Waiting: {counts['proposals']} staged proposal(s) · "
         f"{counts['cases']} open Case(s) · {counts['talk']} open"
         f" dispute(s) · {counts['ideas']} idea(s) — "
         f"{len(items)} item(s) in all."),
        "",
        "## The queue (oldest first)",
        "",
    ]
    if items:
        for n, item in enumerate(items, 1):
            lines.append(f"{n}. {item['date'].isoformat()} — "
                         f"{item['label']} — `{item['source']}`")
    else:
        lines.append("Nothing is waiting on the owner.")
    lines += [
        "",
        "## How an item leaves this queue",
        "",
        "The owner rules on it in chat; the ruling is recorded"
        " where the item lives (the proposal is promoted or"
        " rejected at the gateway, the idea moves on [[ideas]],"
        " the Case is closed by `wiki_cases.py rule`, the talk"
        " page is marked resolved) — and the next generated"
        " queue simply no longer contains it. This page is a"
        " snapshot; regenerating it never edits the sources.",
        "",
    ]
    return "\n".join(lines)


def cmd_queue(args):
    items = build_queue()
    counts = {"proposals": len(queue_proposals()),
              "cases": len(queue_cases()),
              "talk": len(queue_talk()),
              "ideas": len(queue_ideas())}
    run_date = args.date or date.today().isoformat()
    out = Path(args.out) if args.out else \
        FILINGS / f"adjudication-queue-{run_date}.md"
    out.write_text(render_queue(items, run_date, counts),
                   encoding="utf-8")
    print(f"wrote {out} — {len(items)} item(s): "
          f"{counts['proposals']} proposal(s), "
          f"{counts['cases']} open case(s), "
          f"{counts['talk']} dispute(s), "
          f"{counts['ideas']} idea(s)")
    return 0


# -- main ---------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Contradiction Cases + adjudication queue")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open", help="classify + record a candidate")
    p.add_argument("--fact", required=True)
    p.add_argument("--page-a", required=True)
    p.add_argument("--text-a", required=True)
    p.add_argument("--as-of-a", default=None)
    p.add_argument("--page-b", default=None)
    p.add_argument("--text-b", default=None)
    p.add_argument("--as-of-b", default=None)
    p.add_argument("--source", default="manual")
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None)
    p.set_defaults(fn=cmd_open)

    p = sub.add_parser("list", help="list Cases by status")
    p.add_argument("--status", default="open")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("rule", help="record the owner's ruling")
    p.add_argument("--case", required=True)
    p.add_argument("--ruling", required=True)
    p.add_argument("--winner", default=None,
                   choices=[None, "a", "b", "neither"])
    p.add_argument("--date", default=None)
    p.set_defaults(fn=cmd_rule)

    p = sub.add_parser("queue", help="generate the queue filing")
    p.add_argument("--date", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_queue)

    args = ap.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
