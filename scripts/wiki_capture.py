#!/usr/bin/env python3
"""wiki_capture.py — capture templates: named destinations,
harness-filled provenance (WikiCitadel v1).

The specification is the org-capture template grammar
(find 3 — GPL source, IDEAS ONLY, re-implemented here in our own
code): a capture lands from a NAMED template at a NAMED
destination; the metadata that matters (timestamp, provenance
link, source fields) is filled by the harness at invocation,
because invocation is the only moment some of it exists; and
the prompts ask only for what the harness cannot know — in
the capture templates proper the one designed prompt is Why;
the filing kind instead carries the filing order's own field
grammar, whose What happened / Evidence fields do that work.

Templates live in templates/capture/<kind>.md and are written
in the grammar this tool expands:

    %U          the capture timestamp (harness)
    %:date      the capture date, YYYY-MM-DD (harness)
    %:title     the title given at invocation
    %:by        who captured (invocation; default agent)
    %:kind      the capture kind
    %:destination  the kind's named destination
    %:decided   (decision kind) the ruling date given at
                invocation, else a TODO prompt — dual dating
                is structural for decisions (governing rule 4)
    %a          the provenance link given at invocation
                (--provenance); absent one, a TODO prompt,
                because provenance exists only at invocation
    %^{...}     a prompt: expands to [prompt: ...] in the
                draft. Two roles only: the artefact slot (the
                thing captured itself — org's %i role) and the
                single designed question, Why.
    %?          where the capturer's writing starts; expands
                to an HTML comment marker
    %%          a literal percent sign

The kinds are the corpus's real intake doors, no more:

    source-note  a thing read at the owner's direction
    filing       an agent's contribution, in the standing
                 [[agent-filing-order]] shape — the draft is
                 staged only; a filing exists when it is SENT
                 through the filings channel, and this tool
                 writes nothing to raw/filings/ or the ledgers
    decision     an owner ruling made or reversed
    idea         an undirected idea for [[ideas]] Waiting
    note         a session observation ([[capture-rules]])

Every draft renders to staging/captures/ — NEVER into wiki/.
Its frontmatter is pre-filled to schema: status at the honest
floor (draft), confidence observed (the capturer was there),
sources empty — never faked. The compile-stamp keys
are present and EMPTY: a capture is not yet a compile, and
scripts/wiki_stamp.py fills them at compile time. The item-51
sensitivity question rides as a marked TODO in the frontmatter:
while it stands unanswered the draft is unclassified, and the
ingest converter (scripts/wiki_convert.py --sensitivity)
refuses unclassified material a home in raw/ — enforcement
stays there; this tool asks the question at capture, where
answering it is cheapest.

Capture remains a DELIBERATE act: this tool renders a draft
when invoked and does nothing else — no watching, no ambient
capture, no auto-filing (the lane constraint).

    python3 scripts/wiki_capture.py list
    python3 scripts/wiki_capture.py new <kind> --title "..."
        [--by NAME] [--provenance LINK] [--decided YYYY-MM-DD]
        [--file NAME]

Exit codes: 0 ok · 1 refusal · 2 usage error.
"""
import argparse
import re
import sys
from datetime import date as _date
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path("templates/capture")
CAPTURE_DIR = Path("staging/captures")

KINDS = {
    "source-note": {
        "template": "source-note.md",
        "destination": "wiki/sources/ (compiled at ingest "
                       "from the raw record)",
        "when": "a thing read at the owner's direction — an "
                "article, a page, a document, an export — that "
                "will become a source page",
    },
    "filing": {
        "template": "filing.md",
        "destination": "the filings flow — email to "
                       "agent@example.com in the "
                       "[[agent-filing-order]] shape; preserved "
                       "verbatim under raw/filings/<agent>/ on "
                       "pickup, ledgered on the sender's "
                       "wiki/filings/ page",
        "when": "an agent's contribution: a fact learned, work "
                "done, a correction, a proposal — drafted here, "
                "a filing only when sent",
    },
    "decision": {
        "template": "decision.md",
        "destination": "evaluation/decisions-register.jsonl + "
                       "the human decision record + wiki/log.md, "
                       "entered at integration",
        "when": "an owner ruling made, or an earlier ruling "
                "reversed (capture triggers 1-2)",
    },
    "idea": {
        "template": "idea.md",
        "destination": "wiki/ideas.md — the Waiting section, "
                       "one line, appended at integration",
        "when": "an undirected idea that must wait for the "
                "owner's call (the ask-first rule)",
    },
    "note": {
        "template": "note.md",
        "destination": "wiki/filings/, or the page the note "
                       "touches, + wiki/log.md — at integration",
        "when": "a session observation: something measured or "
                "verified, a commitment given, a grey-zone "
                "capture under [[capture-rules]]",
    },
}

PROMPT_RE = re.compile(r"%\^\{([^}]*)\}")
KEYWORD_RE = re.compile(r"%:([a-z_]+)")
TOKEN_LEFTOVER_RE = re.compile(r"%[:^Ua\?]|%\{")


class CaptureError(Exception):
    pass


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:60].strip("-")
    return slug or "untitled"


def _timestamp(now):
    return now.strftime("%Y-%m-%d %H:%M %Z")


def expand(template_text, values):
    """Expand the capture grammar. `values` carries the
    harness/invocation fills: title, by, kind, destination,
    provenance (None when not supplied), decided (None when
    not supplied)."""
    text = template_text.replace("%%", "\x00")

    def prompt(m):
        return "[prompt: %s]" % m.group(1).strip()

    text = PROMPT_RE.sub(prompt, text)

    def keyword(m):
        key = m.group(1)
        if key == "date":
            return values["date"]
        if key == "decided":
            if values.get("decided"):
                return values["decided"]
            return ("TODO (prompt: the date the ruling was "
                    "made, if not the capture date — dual "
                    "dating is not optional)")
        if key in ("title", "by", "kind", "destination"):
            return values[key]
        raise CaptureError("template uses unknown keyword "
                           "%%:%s" % key)

    text = KEYWORD_RE.sub(keyword, text)
    text = text.replace("%U", values["timestamp"])
    if values.get("provenance"):
        text = text.replace("%a", values["provenance"])
    else:
        text = text.replace(
            "%a",
            "TODO (prompt: provenance — the page, place, "
            "person or message this was captured from)")
    text = text.replace("%?", "<!-- write from here -->")
    text = text.replace("\x00", "%")
    leftover = TOKEN_LEFTOVER_RE.search(text)
    if leftover:
        raise CaptureError("template left an unexpanded token "
                           "at %r" % leftover.group(0))
    return text


def render(kind, title, by="agent", provenance=None,
           decided=None, now=None, root=ROOT):
    if kind not in KINDS:
        raise CaptureError(
            "unknown capture kind %r; the kinds are: %s"
            % (kind, ", ".join(sorted(KINDS))))
    if decided and kind != "decision":
        raise CaptureError("--decided belongs to the decision "
                           "kind only")
    if decided:
        try:
            _date.fromisoformat(decided)
        except ValueError:
            raise CaptureError("--decided must be YYYY-MM-DD, "
                               "got %r" % decided)
    if not title or not title.strip():
        raise CaptureError("a capture needs a --title")
    spec = KINDS[kind]
    template_path = root / TEMPLATE_DIR / spec["template"]
    if not template_path.exists():
        raise CaptureError("capture template missing: %s"
                           % template_path)
    now = now or datetime.now().astimezone()
    values = {
        "timestamp": _timestamp(now),
        "date": now.strftime("%Y-%m-%d"),
        "title": title.strip().replace('"', "'"),
        "by": by,
        "kind": kind,
        "destination": spec["destination"],
        "provenance": provenance,
        "decided": decided,
    }
    return expand(template_path.read_text(encoding="utf-8"),
                  values)


def new_capture(kind, title, by="agent", provenance=None,
                decided=None, file=None, now=None, root=ROOT):
    """Render a capture draft into staging/captures/ and return
    its repo-relative path. Refuses anything that would write
    outside staging/captures/."""
    now = now or datetime.now().astimezone()
    text = render(kind, title, by=by, provenance=provenance,
                  decided=decided, now=now, root=root)
    if file:
        if Path(file).is_absolute() or "/" in file \
                or "\\" in file or ".." in file:
            raise CaptureError(
                "--file takes a bare file name; drafts live "
                "flat in staging/captures/ — got %r" % file)
        name = file if file.endswith(".md") else file + ".md"
    else:
        name = "%s-%s-%s.md" % (now.strftime("%Y-%m-%d"), kind,
                                slugify(title))
    out_dir = root / CAPTURE_DIR
    out = out_dir / name
    if out.exists():
        raise CaptureError("capture draft already exists: %s "
                           "(choose another --file)"
                           % (CAPTURE_DIR / name))
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return str(CAPTURE_DIR / name)


def list_kinds():
    lines = []
    for kind in sorted(KINDS):
        spec = KINDS[kind]
        lines.append("%s" % kind)
        lines.append("  destination: %s" % spec["destination"])
        lines.append("  when: %s" % spec["when"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("new")
    p.add_argument("kind")
    p.add_argument("--title", required=True)
    p.add_argument("--by", default="agent")
    p.add_argument("--provenance")
    p.add_argument("--decided")
    p.add_argument("--file")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            print(list_kinds())
        else:
            rel = new_capture(args.kind, args.title, by=args.by,
                              provenance=args.provenance,
                              decided=args.decided, file=args.file,
                              root=args.root)
            print("capture draft: %s" % rel)
            print("staged only — nothing was filed; the "
                  "sensitivity TODO in its frontmatter must be "
                  "answered before it can be ingested.")
    except CaptureError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
