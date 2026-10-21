#!/usr/bin/env python3
"""wiki_reflexion.py — Reflexion post-failure notes
(Marathon R5 lane BB).

Pattern: Shinn et al., "Reflexion: Language Agents with
Verbal Reinforcement Learning" (CC BY 4.0) — after a failed
attempt, the agent writes a short verbal reflection on what
failed and what to do differently, and keeps it where the
next attempt will see it. Re-implemented deterministically
in our own code: NO model calls anywhere. The reflection's
"what to do differently" is drawn from a FIXED table keyed
by a fixed cause-class vocabulary — the note is composed,
never generated.

Where failures already live in this wiki's machinery (the
wiring points this tool reads):
  * the Ask door's records — wiki/access/qa-*.jsonl lines
    whose status is not "answered" (abstentions and failures
    recorded by tools/ask/pickup.py), and the abstention
    battery's failing cases;
  * the ingest path — evaluation/ingest-queue.jsonl events
    of kind "failed" (scripts/wiki_ingest_queue.py's
    append-only register);
  * evaluation/post-mortems.jsonl entries (the register
    scripts/wiki_postmortem.py maintains) — a post-mortem is
    already a failure record; `draft` turns one into the
    short note form for the affected page's log.

The note format (one note, appended under a page's
`## Reflection notes` section — created at the end of the
page when absent — or, with --to-log, as an entry in
wiki/log.md's append-only stream):

    - [YYYY-MM-DD] reflexion | <subject>
      - Failed: <what failed, one line>
      - Cause class: <one of the fixed vocabulary>
      - Evidence: <record the failure is read from>
      - Do differently: <the fixed next action for the class>

RECORDS, NEVER BEHAVIOUR: a note changes nothing about how
any tool runs. Appending one is an explicit act (`append`
requires --apply; the default is a dry-run that prints the
note and writes nothing), notes are append-only (existing
notes are never rewritten or removed by this tool), and a
note that names a rule change is a proposal on the page —
the rule itself changes only through its own machinery.

    python3 scripts/wiki_reflexion.py draft --what-failed W
        --cause-class C --evidence E [--subject S]
    python3 scripts/wiki_reflexion.py append --page wiki/x.md
        --what-failed W --cause-class C --evidence E [--apply]
        [--date YYYY-MM-DD] [--root DIR]
    python3 scripts/wiki_reflexion.py scan [--root DIR]
        (report failure records found at the wiring points;
        writes nothing)

Exit codes: 0 ok · 1 scan found failure records · 2 usage
error (unknown cause class, missing page, bad record).
Stdlib only. Importable in-process (tests drive the
functions against fixture roots).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CAUSE_CLASSES = (
    "missing-evidence",
    "citation-drift",
    "source-unreadable",
    "contract-violation",
    "superseded-claim",
    "transport-failure",
    "scope-error",
    "unknown",
)

# The fixed "do differently" table — the whole of this tool's
# judgement, stated as data so a reader can audit it. A class
# not in the table is refused, never improvised.
DO_DIFFERENTLY = {
    "missing-evidence":
        "Abstain and record the gap; do not answer from "
        "thinner evidence next time — file the gap as a "
        "research-log not-found entry instead.",
    "citation-drift":
        "Re-run the cite-lock check on the affected page and "
        "re-verify each moved or changed citation against the "
        "current source text before relying on the claim.",
    "source-unreadable":
        "Route the source through conversion/OCR verification "
        "before compiling from it; never rest a cited claim on "
        "an unreadable source.",
    "contract-violation":
        "Re-check the record against the answer contract "
        "before filing; a record that fails the contract is "
        "refused, not repaired after the fact.",
    "superseded-claim":
        "Run the claim-match screen before compiling; a "
        "restated superseded form inherits its settled "
        "standing at capture, never a fresh clean record.",
    "transport-failure":
        "Treat the failure as a statement about the door, "
        "never about the evidence; retry through a different "
        "door and record which door failed.",
    "scope-error":
        "Re-read the approved item's exact text and audit the "
        "work element by element against it before reporting "
        "anything built.",
    "unknown":
        "Classify the failure before retrying; an unclassified "
        "failure is recorded as unknown and surfaced, not "
        "silently retried.",
}

SECTION_HEADING = "## Reflection notes"


class ReflexionError(Exception):
    pass


def make_note(what_failed: str, cause_class: str, evidence: str,
              subject: str, on: str) -> str:
    """The note text for one failure (no trailing newline).
    Deterministic: same inputs, same note."""
    if cause_class not in DO_DIFFERENTLY:
        raise ReflexionError(
            f"unknown cause class {cause_class!r}; the "
            f"vocabulary is: {', '.join(CAUSE_CLASSES)}")
    for name, val in (("what-failed", what_failed),
                      ("evidence", evidence),
                      ("subject", subject)):
        if not val or not str(val).strip():
            raise ReflexionError(f"{name} must be non-empty")
    return (
        f"- [{on}] reflexion | {subject}\n"
        f"  - Failed: {what_failed.strip()}\n"
        f"  - Cause class: {cause_class}\n"
        f"  - Evidence: {evidence.strip()}\n"
        f"  - Do differently: {DO_DIFFERENTLY[cause_class]}")


def classify_failure(record: dict) -> str:
    """A deterministic cause class for a failure record from
    one of the wiring points, from the record's own fields —
    keyword classes over its stated reason/status, else
    `unknown`. Stated as data-order rules, first match wins."""
    # An explicit root_cause_class on the record outranks
    # keyword guessing over long prose (a post-mortem's
    # narrative mentions many failure words it is not about).
    rcc = str(record.get("root_cause_class") or "").lower()
    if rcc:
        if rcc in ("scope", "scope-error"):
            return "scope-error"
        text = rcc + " " + str(record.get("title") or "").lower()
    else:
        text = " ".join(str(record.get(k) or "") for k in
                        ("reason", "fail_reason", "abstention_reason",
                         "status", "kind")).lower()
    rules = (
        ("superseded-claim", ("supersed", "retired claim")),
        ("citation-drift", ("citation", "cite", "moved",
                            "changed source")),
        ("source-unreadable", ("unreadable", "ocr", "pdf",
                               "extraction")),
        ("contract-violation", ("contract", "abstain",
                                "no evidence", "no corpus")),
        ("transport-failure", ("transport", "connection",
                               "timeout", "door-failed")),
        ("scope-error", ("scope", "narrower than")),
        ("missing-evidence", ("missing", "not found",
                              "not-found", "no source")),
    )
    if "abstain" in text or "no evidence" in text \
            or "no corpus" in text:
        return "missing-evidence"
    for cls, keys in rules:
        if any(k in text for k in keys):
            return cls
    return "unknown"


def append_note(page_text: str, note: str) -> str:
    """Page text with *note* appended under its Reflection
    notes section (the section is created at the end when
    absent). Append-only: existing content is preserved
    byte-for-byte before the insertion point."""
    if SECTION_HEADING in page_text:
        idx = page_text.index(SECTION_HEADING)
        rest = page_text[idx + len(SECTION_HEADING):]
        nxt = re.search(r"\n## ", rest)
        if nxt:
            at = idx + len(SECTION_HEADING) + nxt.start()
            head = page_text[:at].rstrip("\n")
            return head + "\n" + note + "\n" + page_text[at:]
        return page_text.rstrip("\n") + "\n" + note + "\n"
    sep = "" if page_text.endswith("\n") else "\n"
    return (page_text + sep + "\n" + SECTION_HEADING + "\n\n"
            + note + "\n")


def scan_failures(root: Path) -> dict:
    """Failure records at the wiring points. Report-only."""
    found = []
    qa_dir = root / "wiki" / "access"
    if qa_dir.is_dir():
        for f in sorted(qa_dir.glob("qa-*.jsonl")):
            for i, line in enumerate(
                    f.read_text(encoding="utf-8",
                                errors="ignore").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("status") not in (None, "answered"):
                    found.append({
                        "wiring": "ask-door",
                        "record": f"{f.relative_to(root)}#{i}",
                        "subject": rec.get("id") or f"line {i}",
                        "cause_class": classify_failure(rec),
                        "what_failed": (rec.get("abstention_reason")
                                        or rec.get("status") or "")})
    queue = root / "evaluation" / "ingest-queue.jsonl"
    if queue.is_file():
        for i, line in enumerate(
                queue.read_text(encoding="utf-8",
                                errors="ignore").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == "failed":
                found.append({
                    "wiring": "ingest-queue",
                    "record": f"evaluation/ingest-queue.jsonl#{i}",
                    "subject": rec.get("id") or f"line {i}",
                    "cause_class": classify_failure(rec),
                    "what_failed": rec.get("reason") or "ingest "
                                    "item failed"})
    pms = root / "evaluation" / "post-mortems.jsonl"
    if pms.is_file():
        for i, line in enumerate(
                pms.read_text(encoding="utf-8",
                                errors="ignore").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("id"):
                found.append({
                    "wiring": "post-mortems",
                    "record": f"evaluation/post-mortems.jsonl#{i}",
                    "subject": rec["id"],
                    "cause_class": classify_failure(rec),
                    "what_failed": rec.get("title") or
                    "post-mortem entry"})
    return {"tool": "scripts/wiki_reflexion.py",
            "kind": "reflexion-failure-scan",
            "date": str(date.today()), "failures": found,
            "count": len(found), "writes": 0}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draft", "append"):
        p = sub.add_parser(name)
        p.add_argument("--what-failed", required=True)
        p.add_argument("--cause-class", required=True,
                       choices=CAUSE_CLASSES)
        p.add_argument("--evidence", required=True,
                       help="the record the failure is read from")
        p.add_argument("--subject", default=None,
                       help="note subject (default: the page "
                            "stem, or 'failure' for draft)")
        p.add_argument("--date", default=None)
        if name == "append":
            p.add_argument("--page", required=True,
                           help="repo-relative page to append to")
            p.add_argument("--apply", action="store_true",
                           help="write the note (default: "
                                "dry-run, print only)")
    sub.add_parser("scan", help="report failure records at the "
                                "wiring points; writes nothing")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "scan":
        report = scan_failures(root)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["count"] else 0
    on = args.date or str(date.today())
    subject = args.subject or (
        Path(args.page).stem if args.cmd == "append" else "failure")
    try:
        note = make_note(args.what_failed, args.cause_class,
                         args.evidence, subject, on)
    except ReflexionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.cmd == "draft":
        print(note)
        return 0
    page = root / args.page
    if not page.is_file():
        print(f"no such page: {args.page}", file=sys.stderr)
        return 2
    if not args.apply:
        print("DRY-RUN — nothing written. Note that --apply "
              "would append to " + args.page + ":\n\n" + note)
        return 0
    page.write_text(append_note(
        page.read_text(encoding="utf-8"), note), encoding="utf-8")
    print(f"appended reflexion note to {args.page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
