#!/usr/bin/env python3
"""Justification trails for headings: NACO 670/675 in wiki
form (WikiCitadel v1).

The pattern is find 2 of the LIS-practice survey
(docs/research-notes.md):
in NACO authority work, field 670 ("Source Data Found")
cites each source that DID yield the established form,
quoting the exact form and where; field 675 ("Source Data
Not Found") cites the sources consulted that yielded
nothing. The record carries its own evidence — including
the dead ends — so a later worker never re-runs a search
that already came back empty, and never has to ask "why
this form?".

Here, an established heading (an entity name, a concept
title, a form other pages rely on) carries a
``## Justification`` section in the BODY of its page:

    ## Justification

    ### Form: Jane Doe

    - Found: "Jane Doe (01/01/1900)" —
      raw/.../digest-000.md#L456 — the family list as the
      owner gave it.
    - Not found: raw/sources/vault/ — searched
      2030-01-01 (grep for "Jane Doe" across the whole
      mirrored vault): no match.
    - Established: 2030-01-01 · by: agent

Why the body, not frontmatter: the frontmatter is
schema-validated (the validator enforces its fields, and
the schema kept that surface tight on purpose), while body
sections are this corpus's established home for appended
evidence blocks — the "## Trust and standing"
sections on source pages are the precedent. A body section
also renders in the Lens and reads as prose. Source
references are written as plain path + line-range text,
NOT as ^[cite:] claim markers: the citation lockfile's
scope is claims, and justification references must not
enter it.

Rules the tool enforces:

  * Entries are appended, never rewritten. ``add`` either
    appends a new ``### Form:`` block at the end of the
    section (creating the section, with its preamble, when
    the page has none) or appends new evidence lines to an
    existing form's block just before its Established line;
    every pre-existing line survives byte-for-byte.
  * A Not found line must name the actual search: what was
    searched and when. ``add`` refuses a --not-found value
    that does not contain "searched YYYY-MM-DD", and the
    parser flags any on-page Not found line lacking one.
    A negative claim without a search behind it is not
    evidence; it is a rumour with good posture.

Commands:

  show <page>            print the page's trail, parsed
  check                  list authority pages with no
                         trail + trails with defects
                         (surfacing only; always exit 0)
  add <page> --form F --found "..." [--not-found "..."]
      --established YYYY-MM-DD --by WHO

<page> is a repo-relative path or a page stem resolved
under wiki/ (e.g. ``jane-doe`` -> wiki/entities/jane-doe.md).

The authority set for ``check``: every page under
wiki/entities/ plus EXTRA_AUTHORITY below (deployments may
name extra authority pages, e.g. a founding session's
compiled record).
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"

# Deployments may name extra authority pages here, e.g.
# ["wiki/sources/founding-session.md"].
EXTRA_AUTHORITY = []

SECTION_HEADING = "## Justification"
FORM_PREFIX = "### Form: "
SEARCHED_RE = re.compile(r"searched \d{4}-\d{2}-\d{2}")


def resolve_page(arg):
    """A repo-relative path, or a stem resolved under wiki/."""
    p = ROOT / arg
    if p.is_file():
        return p
    hits = sorted(WIKI.rglob(arg + ".md"))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no such page: {arg}")
    raise SystemExit(
        f"ambiguous stem {arg!r}: " + ", ".join(
            str(h.relative_to(ROOT)) for h in hits))


# -- parsing ----------------------------------------------------------------

def parse_trail(text):
    """Parse a page's ## Justification section.

    Returns None when the page has no such section, else a
    list of entries: {form, found: [...], not_found: [...],
    established: str|None, unsearched_not_found: int}.
    Line grammar is the one in the module docstring; lines
    that match nothing are ignored (prose may live in the
    section — the preamble does).
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == SECTION_HEADING:
            start = i
            break
    if start is None:
        return None
    entries = []
    cur = None
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if ln.startswith(FORM_PREFIX):
            cur = {"form": ln[len(FORM_PREFIX):].strip(),
                   "found": [], "not_found": [],
                   "established": None,
                   "unsearched_not_found": 0}
            entries.append(cur)
            continue
        if cur is None:
            continue
        s = ln.strip()
        if s.startswith("- Found:"):
            cur["found"].append(s[len("- Found:"):].strip())
        elif s.startswith("- Not found:"):
            val = s[len("- Not found:"):].strip()
            cur["not_found"].append(val)
            if not SEARCHED_RE.search(val):
                cur["unsearched_not_found"] += 1
        elif s.startswith("- Established:"):
            cur["established"] = s[len("- Established:"):].strip()
    return entries


# -- rendering --------------------------------------------------------------

def display(page):
    try:
        return str(page.relative_to(ROOT))
    except ValueError:
        return str(page)


def render(page, entries):
    out = [f"# Justification trail — {display(page)}", ""]
    if entries is None:
        out.append("No ## Justification section on this page.")
        return "\n".join(out)
    if not entries:
        out.append("Section present; no form entries yet.")
        return "\n".join(out)
    for e in entries:
        out.append(f"Form: {e['form']}")
        for f in e["found"]:
            out.append(f"  found (670):     {f}")
        for n in e["not_found"]:
            flag = "" if SEARCHED_RE.search(n) else \
                "  [NO SEARCH RECORDED]"
            out.append(f"  not found (675): {n}{flag}")
        if e["established"]:
            out.append(f"  established:     {e['established']}")
        out.append("")
    return "\n".join(out).rstrip()


# -- check ------------------------------------------------------------------

def authority_pages():
    pages = sorted((WIKI / "entities").glob("*.md"))
    pages += [ROOT / rel for rel in EXTRA_AUTHORITY]
    return pages


def cmd_check(_args):
    missing, defective = [], []
    for page in authority_pages():
        rel = page.relative_to(ROOT)
        if not page.is_file():
            missing.append(f"{rel} (page not on disk)")
            continue
        entries = parse_trail(page.read_text(encoding="utf-8"))
        if entries is None:
            missing.append(str(rel))
            continue
        for e in entries:
            if e["unsearched_not_found"]:
                defective.append(
                    f"{rel} — form {e['form']!r}: "
                    f"{e['unsearched_not_found']} Not found "
                    "line(s) name no search (no 'searched "
                    "YYYY-MM-DD')")
            if not e["found"]:
                defective.append(
                    f"{rel} — form {e['form']!r}: no Found "
                    "line (a heading justified only by "
                    "absences is not justified)")
    print("Justification-trail check (surfacing only)")
    print(f"  authority pages checked: {len(authority_pages())}")
    print(f"  without a trail: {len(missing)}")
    for m in missing:
        print(f"    - {m}")
    print(f"  defective entries: {len(defective)}")
    for d in defective:
        print(f"    - {d}")
    return 0


# -- add --------------------------------------------------------------------

def section_bounds(lines):
    """(start, end) line indexes of the Justification
    section's body: start is the heading line, end is the
    index one past the last section line."""
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == SECTION_HEADING:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def cmd_add(args):
    for nf in args.not_found or []:
        if not SEARCHED_RE.search(nf):
            print("REFUSED: a Not found record must name the "
                  "actual search — what was searched and "
                  "when ('searched YYYY-MM-DD ...'). A "
                  "negative claim without a search behind "
                  "it is not evidence.", file=sys.stderr)
            return 2
    if not args.found and not args.not_found:
        print("REFUSED: nothing to append (give --found "
              "and/or --not-found).", file=sys.stderr)
        return 2
    page = resolve_page(args.page)
    text = page.read_text(encoding="utf-8")
    lines = text.splitlines()
    bounds = section_bounds(lines)
    evidence = [f"- Found: {f}" for f in args.found or []]
    evidence += [f"- Not found: {n}" for n in args.not_found or []]
    if bounds is None:
        block = ["", SECTION_HEADING, "",
                 "Justification trails (NACO 670/675 pattern, "
                 "WikiCitadel v1): each established "
                 "form below",
                 "carries where it was found (670) and where it "
                 "was sought",
                 "and not found (675). The negative searches are "
                 "evidence —",
                 "they stop the next agent re-running them. "
                 "Entries are",
                 "appended, never rewritten "
                 "(`scripts/wiki_justify.py`).",
                 "", FORM_PREFIX + args.form, ""]
        block += evidence
        block.append(f"- Established: {args.established} · "
                     f"by: {args.by}")
        new_text = text.rstrip("\n") + "\n" + "\n".join(block) + "\n"
        page.write_text(new_text, encoding="utf-8")
        print(f"added trail + form {args.form!r} to "
              f"{page.relative_to(ROOT)}")
        return 0
    start, end = bounds
    # find this form's block inside the section
    form_at = None
    for i in range(start + 1, end):
        if lines[i].startswith(FORM_PREFIX) and \
                lines[i][len(FORM_PREFIX):].strip() == args.form:
            form_at = i
            break
    if form_at is None:
        block = ["", FORM_PREFIX + args.form, ""]
        block += evidence
        block.append(f"- Established: {args.established} · "
                     f"by: {args.by}")
        insert_at = end
        # keep a trailing blank line structure tidy: insert
        # before any run of trailing blank lines is fine too;
        # appending at the section end is the rule.
        lines[insert_at:insert_at] = block
        page.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"added form {args.form!r} to "
              f"{page.relative_to(ROOT)}")
        return 0
    # existing form: append evidence lines before its
    # Established line (or at the block's end); no existing
    # line is modified.
    block_end = end
    for j in range(form_at + 1, end):
        if lines[j].startswith(FORM_PREFIX):
            block_end = j
            break
    insert_at = block_end
    for j in range(form_at + 1, block_end):
        if lines[j].strip().startswith("- Established:"):
            insert_at = j
            break
    lines[insert_at:insert_at] = evidence
    page.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"appended {len(evidence)} evidence line(s) to "
          f"form {args.form!r} in {page.relative_to(ROOT)}")
    return 0


# -- main -------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Justification trails for headings "
                    "(NACO 670/675 pattern).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_show = sub.add_parser("show", help="print a page's trail")
    p_show.add_argument("page")
    sub.add_parser("check", help="list authority pages "
                                 "without trails (surfacing)")
    p_add = sub.add_parser("add", help="append a record")
    p_add.add_argument("page")
    p_add.add_argument("--form", required=True)
    p_add.add_argument("--found", action="append",
                       help='"exact form" — path#Lx-Ly — note')
    p_add.add_argument("--not-found", action="append",
                       help="place — searched YYYY-MM-DD "
                            "(what was searched): result")
    p_add.add_argument("--established", required=True)
    p_add.add_argument("--by", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "show":
        page = resolve_page(args.page)
        print(render(page, parse_trail(
            page.read_text(encoding="utf-8"))))
        return 0
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "add":
        return cmd_add(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
