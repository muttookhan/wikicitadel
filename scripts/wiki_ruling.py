#!/usr/bin/env python3
"""Owner rulings in chat — the applier (WikiCitadel v1).

Rulings are the owner's replies in chat: the agent records the
ruling and runs this tool to apply it to wiki/ideas.md. The Lens
Briefing's "Waiting on you" list is read-only and sends nothing —
the Approve / Reject buttons it briefly carried were retired by
the owner's direction (schema: AGENTS.md, "Owner rulings in
chat"). The path is: owner's chat reply -> agent records it ->
this tool -> ideas.md move + log line.

Usage:
  python3 scripts/wiki_ruling.py apply --decision approved|rejected \
          --title "<exact bold title>" [--date YYYY-MM-DD] [--dry-run]

The tool finds the single-line bullet in the "## Waiting for
your call" section of wiki/ideas.md whose bold lead equals
--title EXACTLY, and moves that whole line to the END of the
"## Approved" section (approved) or the "## Disapproved"
section (rejected), appending the ruling marker to the moved
line:

  " — **APPROVED by the owner in chat, <date>**"
  " — **REJECTED by the owner in chat, <date>**"

  (Rulings applied while the buttons lived carry the retired
  "via the Lens ruling button" marker; that marker is history
  and is still recognised for idempotency — see below.)

--date defaults to today in the owner's timezone
(OWNER_TZ below — set it for your deployment).
Every other byte of the file is preserved.

Fail-closed rules — a ruling is never guessed:
  * No exact match in Waiting, but the title stands in Approved
    or Disapproved already carrying a ruling marker (either
    the current chat marker or the retired Lens marker):
    print "ALREADY-APPLIED", exit 0, change nothing
    (re-delivery of a ruling is idempotent).
  * Title not found: print "NOT-FOUND", exit 2, file untouched.
  * The matched bullet has continuation lines (following lines
    starting with whitespace before the next bullet/heading):
    print "REFUSED: multi-line bullet", exit 2, file untouched.
  * A needed section heading is missing: print a REFUSED line,
    exit 2, file untouched.

On success the tool prints exactly one log line, which the
pickup appends to wiki/log.md:

  Owner ruling in chat: <title> — APPROVED (Ideas board: Waiting → Approved).
  Owner ruling in chat: <title> — REJECTED (Ideas board: Waiting → Disapproved).

--dry-run computes and prints the same outcome but writes
nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# The owner's timezone — set for your deployment.
OWNER_TZ = ZoneInfo("America/New_York")
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "wiki" / "ideas.md"

WAITING_HEADING = "## Waiting for your call"
APPROVED_HEADING = "## Approved"
DISAPPROVED_HEADING = "## Disapproved"
CHAT_MARKER = "by the owner in chat"
LENS_MARKER = "via the Lens ruling button"  # retired; history only
RULING_MARKERS = (CHAT_MARKER, LENS_MARKER)

BOLD_LEAD = re.compile(r"^- \*\*(.+?)\*\*")

DECISIONS = {
    "approved": ("APPROVED", APPROVED_HEADING, "Approved"),
    "rejected": ("REJECTED", DISAPPROVED_HEADING, "Disapproved"),
}


def find_heading(lines: list[str], heading: str) -> int | None:
    for i, ln in enumerate(lines):
        if ln.rstrip("\r\n").rstrip() == heading:
            return i
    return None


def section_range(lines: list[str], heading_idx: int) -> tuple[int, int]:
    """(start, end) line indices of a section's body: from just
    after its heading to the next '## ' heading or EOF."""
    end = len(lines)
    for j in range(heading_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return heading_idx + 1, end


def bold_lead(line: str) -> str | None:
    m = BOLD_LEAD.match(line)
    return m.group(1) if m else None


def has_continuation(lines: list[str], idx: int, end: int) -> bool:
    """True when the bullet at idx is followed, before the next
    bullet or heading, by a line starting with whitespace that
    carries content — i.e. the bullet is not single-line."""
    for j in range(idx + 1, end):
        ln = lines[j]
        if ln.startswith("- ") or ln.startswith("#"):
            return False
        if ln[:1] in (" ", "\t") and ln.strip():
            return True
    return False


def apply_ruling(lines: list[str], decision: str, title: str,
                 date: str) -> tuple[list[str] | None, str, str]:
    """Pure core. Returns (new_lines, outcome, message):
    outcome "applied"   -> new_lines is the edited file, message
                           is the log line for wiki/log.md;
    outcome "already"   -> message "ALREADY-APPLIED";
    outcome "not-found" -> message "NOT-FOUND";
    outcome "refused"   -> message "REFUSED: ...".
    For every outcome except "applied", new_lines is None and
    the caller must not write."""
    word, target_heading, target_name = DECISIONS[decision]

    waiting_idx = find_heading(lines, WAITING_HEADING)
    if waiting_idx is None:
        return None, "refused", f"REFUSED: no '{WAITING_HEADING}' section"
    w_start, w_end = section_range(lines, waiting_idx)

    match = None
    for i in range(w_start, w_end):
        if bold_lead(lines[i]) == title:
            match = i
            break

    if match is None:
        # Idempotence: the ruling may already stand applied.
        for heading in (APPROVED_HEADING, DISAPPROVED_HEADING):
            h_idx = find_heading(lines, heading)
            if h_idx is None:
                continue
            s, e = section_range(lines, h_idx)
            for i in range(s, e):
                if bold_lead(lines[i]) == title and any(m in lines[i] for m in RULING_MARKERS):
                    return None, "already", "ALREADY-APPLIED"
        return None, "not-found", "NOT-FOUND"

    if has_continuation(lines, match, w_end):
        return None, "refused", "REFUSED: multi-line bullet"

    target_idx = find_heading(lines, target_heading)
    if target_idx is None:
        return None, "refused", f"REFUSED: no '{target_heading}' section"

    moved = (lines[match].rstrip("\r\n").rstrip()
             + f" — **{word} by the owner in chat, {date}**\n")

    new_lines = lines[:match] + lines[match + 1:]
    # The target section follows Waiting, so its indices shifted
    # by the removal — find it again on the edited list.
    t_idx = find_heading(new_lines, target_heading)
    t_start, t_end = section_range(new_lines, t_idx)
    insert_after = t_idx  # empty section: land right under the heading
    for i in range(t_start, t_end):
        if new_lines[i].strip():
            insert_after = i
    new_lines = (new_lines[:insert_after + 1] + [moved]
                 + new_lines[insert_after + 1:])

    log_line = (f"Owner ruling in chat: {title} — {word} "
                f"(Ideas board: Waiting → {target_name}).")
    return new_lines, "applied", log_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply an owner's chat ruling to wiki/ideas.md.")
    sub = parser.add_subparsers(dest="command", required=True)
    ap = sub.add_parser("apply", help="apply one ruling")
    ap.add_argument("--decision", required=True,
                    choices=sorted(DECISIONS))
    ap.add_argument("--title", required=True,
                    help="the item's exact bold lead on the Ideas board")
    ap.add_argument("--date", default=None,
                    help="ruling date, YYYY-MM-DD (default: today, "
                         "owner's timezone)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the outcome; write nothing")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE,
                    help="ideas page to edit (default: wiki/ideas.md)")
    args = parser.parse_args(argv)

    if args.date is not None:
        try:
            date = datetime.strptime(args.date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            print(f"REFUSED: --date must be YYYY-MM-DD, got {args.date!r}",
                  file=sys.stderr)
            return 2
    else:
        date = datetime.now(OWNER_TZ).date().isoformat()

    path: Path = args.file
    with open(path, "r", encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)

    new_lines, outcome, message = apply_ruling(
        lines, args.decision, args.title, date)
    print(message)
    if outcome == "applied":
        if not args.dry_run:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write("".join(new_lines))
        return 0
    if outcome == "already":
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
