#!/usr/bin/env python3
"""Governed observations pass .

Adapted from Hindsight's *observations* (vectorize-io/hindsight,
MIT; assessed in wiki/sources/hindsight.md): Hindsight runs a
background consolidation that deduplicates raw memories into
standing beliefs, each keeping its evidence. Our version is
governed the wiki's way:

  - it reads only the compiled wiki layer (wiki/**/*.md) —
    never raw/, which stays immutable and untouched;
  - it PROPOSES consolidated beliefs in a single filing,
    wiki/filings/observations-<date>.md, marked AWAITING OWNER;
  - nothing it writes is canonical, and it edits no other page.
    An observation becomes part of the wiki only when the owner
    rules on it and the agent compiles it in by hand.

What counts as a citable statement:

  1. a body sentence carrying a claim-level citation marker
     (^[cite: <path>#L<a>-L<b>] — the AGENTS.md convention; the
     regex and the frontmatter parser are reused from
     scripts/wiki_validate.py, the same reuse wiki_claims.py
     makes), or
  2. a frontmatter `claim:` entry (the outcome-verified claim
     lifecycle, scripts/wiki_claims.py).

Statements are grouped when they share the same cited source
(the marker target for type 1, the page's frontmatter `sources`
for type 2) OR the same [[wikilinked]] entity in the statement
text. A group supported by >= 2 distinct pages becomes one
candidate observation:

  - the consolidated statement is ONE member statement, verbatim
    (the longest, ties broken by page then line) — wording is
    never merged or invented by this script;
  - the proof count is the number of distinct supporting pages;
  - the evidence list carries every member statement as
    page + line + a verbatim quote of at most 200 characters.

Deterministic: pages, statements, groups and observations are
all processed in sorted order, so the same wiki always produces
the same filing.

Exclusions (per the filing's remit): wiki/filings/ and
wiki/talk/ (proposal/dispute areas, not compiled knowledge) and
the structural wiki/index.md + wiki/log.md.

Usage:
  python3 scripts/wiki_observe.py            # write the filing
  python3 scripts/wiki_observe.py --dry-run  # print, write nothing

Stdlib only.
"""
import argparse
import importlib.util
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"

_spec = importlib.util.spec_from_file_location(
    "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
_wv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wv)
parse_frontmatter = _wv.parse_frontmatter
as_list = _wv.as_list
CITE_RE = _wv.CITE_RE
CITE_LOOSE_RE = re.compile(r"\^\[cite:[^\]]*\]")

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
SENT_END_RE = re.compile(r"[.!?](?=\s|$)")
QUOTE_MAX = 200

EXCLUDED_DIRS = ("wiki/filings/", "wiki/talk/")
EXCLUDED_FILES = {"wiki/index.md", "wiki/log.md"}


class Statement:
    __slots__ = ("page", "line", "text", "kind", "cite", "links",
                 "source_keys")

    def __init__(self, page, line, text, kind, cite, links, source_keys):
        self.page = page            # repo-relative path of the wiki page
        self.line = line            # 1-based line in that page
        self.text = text            # the statement, markers stripped
        self.kind = kind            # "cite" | "claim"
        self.cite = cite            # "raw/...#L24-L29" for kind == cite
        self.links = links          # wikilink targets named in the text
        self.source_keys = source_keys  # raw paths this statement rests on


def clean_text(s):
    """Collapse whitespace; strip list/heading markers at the start."""
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+)", "", s)
    return s.strip()


def sentence_around(text, start, end):
    """The sentence in `text` containing span [start, end)."""
    lo = 0
    for m in SENT_END_RE.finditer(text, 0, start):
        lo = m.end()
        while lo < len(text) and text[lo] == " ":
            lo += 1
    hi = len(text)
    m = SENT_END_RE.search(text, end)
    if m:
        hi = m.end()
    return text[lo:hi]


def body_paragraphs(text):
    """Yield (start_line, [(line_no, line_text), ...]) per paragraph.

    Line numbers are 1-based against the whole file. Fenced code
    blocks are dropped (a marker quoted in a fence is syntax, not
    a claim — the wiki_validate.py convention).
    """
    m = FM_RE.match(text)
    offset = text[:m.end()].count("\n") if m else 0
    body = text[m.end():] if m else text
    paras, cur = [], []
    in_fence = False
    for i, line in enumerate(body.split("\n")):
        abs_no = offset + i + 1
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if cur:
                paras.append(cur)
                cur = []
            continue
        if in_fence:
            continue
        if line.strip():
            cur.append((abs_no, line))
        elif cur:
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)
    for para in paras:
        yield para[0][0], para


def cite_statements(page, text):
    """Type-1 statements: sentences carrying a ^[cite:] marker."""
    out = []
    for _start, para in body_paragraphs(text):
        # Join the paragraph, remembering where each line begins so
        # a marker's character offset maps back to its file line.
        joined_parts, line_at = [], []
        pos = 0
        for line_no, line_text in para:
            line_at.append((pos, line_no))
            joined_parts.append(line_text.strip())
            pos += len(line_text.strip()) + 1
        joined = " ".join(joined_parts)
        for m in CITE_RE.finditer(joined):
            line_no = max(no for at, no in line_at if at <= m.start())
            sentence = sentence_around(joined, m.start(), m.end())
            sentence = clean_text(CITE_LOOSE_RE.sub("", sentence))
            if not sentence:
                continue
            target = m.group(1)
            rng = f"L{m.group(2)}"
            if m.group(3):
                rng += f"-L{m.group(3)}"
            links = [t.strip() for t in WIKILINK_RE.findall(sentence)]
            out.append(Statement(page, line_no, sentence, "cite",
                                 f"{target}#{rng}", links, [target]))
    return out


def claim_statement(page, text, fields):
    """Type-2 statement: the page's frontmatter claim: entry."""
    claim = str(fields.get("claim") or "").strip()
    if not claim:
        return None
    line_no = 1
    for i, line in enumerate(text.split("\n"), start=1):
        if line.startswith("claim:"):
            line_no = i
            break
    links = [t.strip() for t in WIKILINK_RE.findall(claim)]
    return Statement(page, line_no, claim, "claim", None, links,
                     [s for s in as_list(fields.get("sources")) if s])


def scan_pages():
    pages = []
    for p in sorted(WIKI.rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel in EXCLUDED_FILES or rel.startswith(EXCLUDED_DIRS):
            continue
        pages.append((rel, p.read_text(encoding="utf-8", errors="ignore")))
    return pages


def group_statements(statements):
    """{(kind, key): [Statement]} — kind is 'source' or 'entity'."""
    groups = defaultdict(list)
    for st in statements:
        for src in st.source_keys:
            groups[("source", src)].append(st)
        seen_links = set()
        for link in st.links:
            key = link.strip().lower()
            if key and key not in seen_links:
                seen_links.add(key)
                groups[("entity", key)].append(st)
    return groups


def build_observations(groups):
    """Qualifying groups -> observation dicts, deterministic order."""
    observations = []
    seen_member_sets = set()
    for (kind, key) in sorted(groups, key=lambda k: (0 if k[0] == "source" else 1, k[1])):
        members = sorted(groups[(kind, key)],
                         key=lambda s: (s.page, s.line, s.text))
        pages = sorted({s.page for s in members})
        if len(pages) < 2:
            continue
        member_set = frozenset((s.page, s.line, s.text) for s in members)
        if member_set in seen_member_sets:
            continue
        seen_member_sets.add(member_set)
        representative = sorted(
            members, key=lambda s: (-len(s.text), s.page, s.line))[0]
        observations.append({
            "group_kind": kind,
            "group_key": key,
            "members": members,
            "pages": pages,
            "representative": representative,
        })
    return observations


def quote_of(text):
    if len(text) <= QUOTE_MAX:
        return text
    return text[:QUOTE_MAX - 1].rstrip() + "…"


def page_link(page):
    return f"[[{Path(page).stem}]]"


def render(observations, stats, run_date):
    raw_sources = set()
    for obs in observations:
        for st in obs["members"]:
            raw_sources.update(s for s in st.source_keys
                               if s.startswith("raw/"))
    fm_sources = sorted(raw_sources)
    lines = [
        "---",
        f"title: Observations pass — {run_date} (proposals for the owner)",
        "type: query",
        f"created: {run_date}",
        f"updated: {run_date}",
        "sources:",
    ]
    lines += [f"  - {s}" for s in fm_sources] or ["  []"]
    lines += [
        "tags: [observations, proposal, filings]",
        "status: draft",
        "confidence: observed",
        "---",
        "",
        f"# Observations pass — {run_date}",
        "",
        "> [!warning] AWAITING OWNER — nothing here is canonical",
        "> Generated by the observations pass (`scripts/wiki_observe.py`),"
        " adapted from Hindsight's observations idea under this wiki's"
        " governance: the pass reads the compiled wiki layer, groups"
        " statements that more than one page supports, and files the"
        " consolidations here as PROPOSALS. **Nothing in this file is"
        " part of the wiki's canonical record, and no page has been"
        " changed.** Each observation becomes canonical only if the"
        " owner rules it in; then it is compiled into the proper page"
        " by hand, with its evidence.",
        "",
        f"Scan: {stats['pages']} pages read, {stats['statements']} citable"
        f" statements extracted, {stats['groups']} multi-page groups"
        f" found, {stats['observations']} observations proposed.",
        "",
    ]
    if not observations:
        lines += [
            "No statement is yet supported by two or more pages under"
            " the grouping rules (shared cited source, or shared"
            " wikilinked entity), so this pass proposes nothing.",
            "",
        ]
    for n, obs in enumerate(observations, start=1):
        rep = obs["representative"]
        if obs["group_kind"] == "source":
            grouped_by = f"shared cited source `{obs['group_key']}`"
        else:
            grouped_by = f"shared wikilinked entity [[{obs['group_key']}]]"
        lines += [
            f"## Observation {n} — supported by {len(obs['pages'])} pages",
            "",
            f"**Consolidated statement** (verbatim from {page_link(rep.page)},"
            f" `{rep.page}` line {rep.line}):",
            "",
            f"> {rep.text}",
            "",
            f"**Grouped by:** {grouped_by}  ",
            f"**Proof count:** {len(obs['pages'])} pages  ",
            "**Evidence:**",
            "",
        ]
        for st in obs["members"]:
            cite_note = f" (cites `{st.cite}`)" if st.cite else " (frontmatter claim)"
            lines.append(
                f"- `{st.page}` line {st.line} — “{quote_of(st.text)}”{cite_note}")
        lines.append("")
    lines += [
        "## How to rule on these",
        "",
        "For each observation: rule it in (it gets compiled into the"
        " proper wiki page with this evidence attached), rule it out"
        " (the grouping was coincidence, not one belief), or ask for"
        " the statements to be checked against their raw sources"
        " first. Silence leaves everything here a proposal — nothing"
        " promotes itself.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Governed observations pass: propose consolidated, "
                    "multi-page beliefs for the owner's ruling.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the filing and summary; write nothing")
    args = ap.parse_args(argv[1:])

    pages = scan_pages()
    statements = []
    for rel, text in pages:
        fields, _body = parse_frontmatter(text)
        statements.extend(cite_statements(rel, text))
        if fields:
            cs = claim_statement(rel, text, fields)
            if cs:
                statements.append(cs)
    statements.sort(key=lambda s: (s.page, s.line, s.text))
    groups = group_statements(statements)
    multi = {k: v for k, v in groups.items()
             if len({s.page for s in v}) >= 2}
    observations = build_observations(groups)
    run_date = date.today().isoformat()
    stats = {"pages": len(pages), "statements": len(statements),
             "groups": len(multi), "observations": len(observations)}
    content = render(observations, stats, run_date)

    if args.dry_run:
        print(content)
    else:
        out = WIKI / "filings" / f"observations-{run_date}.md"
        out.write_text(content, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT).as_posix()}")
    print(f"pages scanned: {stats['pages']}   statements: {stats['statements']}"
          f"   multi-page groups: {stats['groups']}"
          f"   observations: {stats['observations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
