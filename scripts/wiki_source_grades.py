#!/usr/bin/env python3
"""Two-axis source grading + source trust labels.

WikiCitadel v1: two patterns from the
feature survey (docs/research-notes.md):

  * ʿIlm al-rijāl (personal lane, find 9): trust is not
    a vibe and not a single score — it is a REGISTRY ENTRY, per
    transmitter, on TWO DISJOINT AXES (ʿadālah, uprightness;
    ḍabṭ, precision), expressed in a FIXED GRADED VOCABULARY,
    kept as a durable reference separate from the reports it
    judges. Adapted here: every wiki source may be graded on
    INTEGRITY (is it what it purports to be; does it assert
    honestly about itself) and PRECISION (how faithfully and
    accurately it transmits), each in its own fixed vocabulary.
  * NewsGuard "Nutrition Labels" (media lane, find 9):
    the LABEL, not the score — a short, structured,
    evidence-backed block on the source page (who is behind it,
    does it correct itself, what it has got wrong here). The
    0–100 numeric score is on the survey's never-build list and
    appears NOWHERE in this tool: the vocabularies contain no
    numbers, and the two axes are never merged into one value.

The register is evaluation/source-grades.jsonl: a header line
(the decisions-register convention), then append-only JSON
lines of two kinds —

  {"kind": "profile", "source": <wiki/sources page>,
   "behind": ..., "corrects": ..., "evidence": [...]}
  {"kind": "grade", "source": <wiki/sources page>,
   "axis": "integrity"|"precision", "grade": <vocabulary>,
   "date": ..., "by": ..., "event": ..., "basis": ...,
   "evidence": [{"ref": <repo path>, "note": ...}, ...]}

A source's current state is the FOLD of its lines: the latest
profile wins, and the latest grade per axis wins. Nothing is
ever rewritten or deleted; a grade changes only by appending
a new grade line resting on a NEW cited event (a correction,
a failed verification, a verified claim) — never by editing
an old line, and never on the source's own testimony alone:
the evidence must be a record on this wiki's side (a pickup
note, a ledger entry, a manifest, a check result).

UNGRADED IS THE DEFAULT, and it is not a criticism: most
sources carry no grade because no cited event supports one
yet. `ungraded` lists them.

Commands:
  show <source>     a source's profile + current grades, with
                    the evidence each grade rests on (accepts
                    a page path or a bare slug)
  ungraded          source pages with no grade on either axis,
                    plus the partially graded (one axis only)
  check             validate the register: structure,
                    vocabularies, and — the point of the tool —
                    that every profile and grade carries at
                    least one evidence ref that resolves
  render <source>   generate the `## Trust and standing` block
                    for a source page from the register, ready
                    for a human/agent to insert (this tool
                    never edits source pages itself)

Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "source-grades.jsonl"
SOURCES_DIR = ROOT / "wiki" / "sources"
LEDGER = ROOT / "wiki" / "rules" / "corrections-ledger.md"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

INTEGRITY = {
    "established": (
        "Established — this source is what it purports to be, "
        "and where this wiki has tested its assertions they "
        "have held."),
    "unremarkable": (
        "Unremarkable — nothing on this wiki's record either "
        "verifies this source specially or tells against it."),
    "questioned": (
        "Questioned — a specific assertion by this source "
        "stands unverified or disputed on this wiki's record; "
        "see the evidence before relying on it."),
    "compromised": (
        "Compromised — this wiki's record shows this source "
        "asserting something false about itself or its "
        "contents; rely on it only with independent "
        "corroboration."),
}
PRECISION = {
    "exact": (
        "Exact — transmission from this source is mechanically "
        "verified (hash or manifest), so what the wiki holds "
        "is what the source held."),
    "careful": (
        "Careful — contents have been checked in use and found "
        "accurate; the errors found were minor."),
    "loose": (
        "Loose — contents include unverified, vendor-stated, "
        "or internally inconsistent material; corroborate "
        "particulars before relying on them."),
    "error-prone": (
        "Error-prone — multiple transmission errors are on "
        "record; treat every particular as suspect until "
        "checked."),
}
AXES = {"integrity": INTEGRITY, "precision": PRECISION}
UNGRADED_PROSE = (
    "Not yet graded — no cited event on this wiki's record "
    "supports a grade yet. Ungraded is the default, not a "
    "criticism.")


# -- register I/O -----------------------------------------------------------

def read_register(path=REGISTER):
    """Return (header, entries): the header dict (or None) and
    the list of profile/grade entry dicts in file order.
    Missing file = (None, []). Malformed lines are returned as
    {"kind": "_bad", "raw": ..., "line": n} so `check` can
    report them instead of crashing."""
    header, entries = None, []
    if not path.is_file():
        return header, entries
    for n, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            entries.append({"kind": "_bad", "raw": line,
                            "line": n})
            continue
        if obj.get("kind") == "header" and header is None:
            header = obj
        else:
            obj["_line"] = n
            entries.append(obj)
    return header, entries


def fold(entries):
    """Fold register entries into current state:
    source -> {"profile": entry|None,
               "grades": {axis: latest grade entry}}."""
    state = {}
    for e in entries:
        if e.get("kind") not in ("profile", "grade"):
            continue
        src = e.get("source")
        if not src:
            continue
        slot = state.setdefault(src, {"profile": None,
                                      "grades": {}})
        if e["kind"] == "profile":
            slot["profile"] = e
        else:
            slot["grades"][e.get("axis")] = e
    return state


def resolve_source(arg):
    """Accept a repo-relative page path or a bare slug and
    return the canonical 'wiki/sources/<slug>.md' form."""
    a = arg.strip()
    if a.startswith("wiki/sources/"):
        return a if a.endswith(".md") else a + ".md"
    if a.endswith(".md"):
        a = a[:-3]
    return f"wiki/sources/{a}.md"


def source_pages():
    if not SOURCES_DIR.is_dir():
        return []
    return sorted(
        f"wiki/sources/{p.name}"
        for p in SOURCES_DIR.glob("*.md"))


# -- check ------------------------------------------------------------------

def check_register(path=REGISTER, root=ROOT):
    """Return a list of problem strings (empty = valid)."""
    problems = []
    if not path.is_file():
        return [f"register missing: {path}"]
    header, entries = read_register(path)
    if header is None:
        problems.append("no header line (kind: header)")
    elif header.get("register") != "source-grades":
        problems.append(
            f"header register is {header.get('register')!r}, "
            "expected 'source-grades'")
    pages = set(source_pages())
    for e in entries:
        n = e.get("_line", "?")
        if e.get("kind") == "_bad":
            problems.append(f"line {n}: not valid JSON")
            continue
        kind = e.get("kind")
        if kind not in ("profile", "grade"):
            problems.append(f"line {n}: unknown kind {kind!r}")
            continue
        src = e.get("source")
        if not src:
            problems.append(f"line {n}: missing source")
            continue
        if src not in pages:
            problems.append(
                f"line {n}: source page not found: {src}")
        ev = e.get("evidence")
        if not isinstance(ev, list) or not ev:
            problems.append(
                f"line {n}: {kind} for {src} carries no "
                "evidence — every entry must cite the record "
                "it rests on")
        else:
            for item in ev:
                if not isinstance(item, dict) \
                        or not item.get("ref"):
                    problems.append(
                        f"line {n}: evidence item without a "
                        f"ref: {item!r}")
                elif not (root / item["ref"]).is_file():
                    problems.append(
                        f"line {n}: evidence ref does not "
                        f"resolve: {item['ref']}")
        if kind == "profile":
            for field in ("behind", "corrects"):
                if not e.get(field):
                    problems.append(
                        f"line {n}: profile for {src} missing "
                        f"{field!r}")
        else:
            axis = e.get("axis")
            if axis not in AXES:
                problems.append(
                    f"line {n}: bad axis {axis!r}")
            elif e.get("grade") not in AXES[axis]:
                problems.append(
                    f"line {n}: grade {e.get('grade')!r} not "
                    f"in the {axis} vocabulary "
                    f"{sorted(AXES[axis])}")
            if not e.get("basis"):
                problems.append(
                    f"line {n}: grade for {src} missing basis")
            if not e.get("by"):
                problems.append(
                    f"line {n}: grade for {src} missing by")
            if not DATE_RE.match(e.get("date", "")):
                problems.append(
                    f"line {n}: grade for {src} has bad date "
                    f"{e.get('date')!r}")
    return problems


# -- render -----------------------------------------------------------------

def ledger_mentions(source):
    """Corrections-ledger entries naming this source page, by
    entry heading. The ledger is prose; a mention is the page
    slug appearing in an entry's section."""
    if not LEDGER.is_file():
        return []
    slug = Path(source).stem
    text = LEDGER.read_text(encoding="utf-8")
    hits = []
    for section in re.split(r"^### ", text, flags=re.M)[1:]:
        heading = section.splitlines()[0].strip()
        if slug in section:
            hits.append(heading)
    return hits


def render_block(source, state):
    slot = state.get(source, {"profile": None, "grades": {}})
    prof = slot["profile"]
    lines = ["## Trust and standing", ""]
    if prof:
        lines.append(f"- **Who is behind it:** {prof['behind']}")
        lines.append(
            f"- **Does it correct itself:** {prof['corrects']}")
    else:
        lines.append(
            "- **Who is behind it:** Not recorded — no profile "
            "entry in `evaluation/source-grades.jsonl`.")
        lines.append(
            "- **Does it correct itself:** Not recorded — no "
            "profile entry in `evaluation/source-grades.jsonl`.")
    for axis in ("integrity", "precision"):
        g = slot["grades"].get(axis)
        label = axis.capitalize()
        if g:
            lines.append(
                f"- **{label}:** {AXES[axis][g['grade']]}")
        else:
            lines.append(f"- **{label}:** {UNGRADED_PROSE}")
    record = []
    for axis in ("integrity", "precision"):
        g = slot["grades"].get(axis)
        if g:
            refs = "; ".join(
                f"`{item['ref']}`" for item in g["evidence"])
            record.append(
                f"{axis} graded {g['grade']} on {g['date']} "
                f"({g['event']}): {g['basis']} Evidence: {refs}.")
    mentions = ledger_mentions(source)
    if mentions:
        record.append(
            "Named in the corrections ledger: "
            + "; ".join(mentions) + ".")
    if record:
        lines.append(
            "- **On this wiki's record:** " + " ".join(record))
    else:
        lines.append(
            "- **On this wiki's record:** Nothing recorded — "
            "no grades, and the corrections ledger does not "
            "name this source.")
    return "\n".join(lines) + "\n"


# -- commands ---------------------------------------------------------------

def cmd_show(args):
    source = resolve_source(args.source)
    _, entries = read_register()
    state = fold(entries)
    slot = state.get(source)
    if slot is None:
        print(f"{source}: no register entries — ungraded on "
              "both axes, no profile.")
        return 0
    print(source)
    prof = slot["profile"]
    if prof:
        print(f"  behind:   {prof['behind']}")
        print(f"  corrects: {prof['corrects']}")
    else:
        print("  profile:  none recorded")
    for axis in ("integrity", "precision"):
        g = slot["grades"].get(axis)
        if not g:
            print(f"  {axis}: ungraded")
            continue
        print(f"  {axis}: {g['grade']} "
              f"({g['date']}, {g['event']}, by {g['by']})")
        print(f"    basis: {g['basis']}")
        for item in g["evidence"]:
            print(f"    evidence: {item['ref']} — "
                  f"{item.get('note', '')}")
    return 0


def cmd_ungraded(args):
    _, entries = read_register()
    state = fold(entries)
    full, partial = [], []
    for page in source_pages():
        slot = state.get(page)
        graded = set(slot["grades"]) if slot else set()
        if not graded:
            full.append(page)
        elif len(graded) == 1:
            missing = ({"integrity", "precision"} - graded).pop()
            partial.append((page, missing))
    print(f"ungraded (no grade on either axis): {len(full)}")
    for p in full:
        print(f"  {p}")
    print(f"partially graded (one axis only): {len(partial)}")
    for p, missing in partial:
        print(f"  {p} — {missing} ungraded")
    return 0


def cmd_check(args):
    problems = check_register()
    if problems:
        print(f"FAIL — {len(problems)} problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    _, entries = read_register()
    state = fold(entries)
    print(f"OK — register valid: {len(entries)} entries, "
          f"{len(state)} sources with entries; every profile "
          "and grade carries resolving evidence.")
    return 0


def cmd_render(args):
    source = resolve_source(args.source)
    if source not in source_pages():
        print(f"no such source page: {source}", file=sys.stderr)
        return 1
    _, entries = read_register()
    state = fold(entries)
    sys.stdout.write(render_block(source, state))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Two-axis source grading + trust labels "
                    "for the LLM Wiki.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="a source's grades + "
                                    "evidence")
    p.add_argument("source")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("ungraded", help="list source pages "
                                        "with no grades")
    p.set_defaults(fn=cmd_ungraded)
    p = sub.add_parser("check", help="validate the register; "
                                     "every entry must cite "
                                     "resolving evidence")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("render", help="generate the Trust and "
                                      "standing block for a "
                                      "source page")
    p.add_argument("source")
    p.set_defaults(fn=cmd_render)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
