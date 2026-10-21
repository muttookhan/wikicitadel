#!/usr/bin/env python3
"""wiki_eval_draft.py — corpus-generated DRAFT eval questions
(Giskard RAGET pattern, Marathon R5 lane BB).

Pattern: Giskard-AI/giskard's RAGET (Apache-2.0) generates
evaluation questions from a corpus so the eval set tracks what
the corpus actually says. Re-implemented deterministically in
our own code: NO model calls anywhere. Candidate questions are
extracted from newly compiled wiki pages — the page title, its
headings, its frontmatter `claim:` and its citation-bearing
sentences — and a candidate is drafted only when its expected
answer occurs verbatim (normalised) in the page it was drafted
from (the answerability discipline of scripts/wiki_golden_builder.py,
reused here for single compiled pages rather than raw sources).

STAGING BOUNDARY (the hard rule of this tool, enforced in code):
  * Output may ONLY be written under `staging/eval-drafts/`.
    Any --out outside that directory is refused (exit 4) —
    including every path under `evaluation/`.
  * Any --out whose name contains `golden-questions` is refused
    outright (exit 4), wherever it points.
  * An existing --out file is never overwritten (exit 4); each
    run drafts a NEW file, so drafts accumulate for review
    instead of silently replacing one another.
  * Every drafted record carries "status": "draft",
    "approved": false and "origin": "wiki_eval_draft" — a
    draft is visibly unapproved on its face. Promotion into
    evaluation/golden-questions.jsonl is a separate owner act
    performed by other machinery; this tool has no code path
    that opens a golden set at all (it never reads one either,
    except the byte-hash guard below).
  * As a tripwire, `draft` hashes evaluation/golden-questions.jsonl
    before and after writing and reports both hashes; if they
    ever differed the run exits 5. (They cannot differ through
    this tool — the guard exists so a future edit that breaks
    the boundary fails loudly instead of silently.)

Deterministic: pages are processed in sorted order, sentences
in page order, ids are sequential (DRAFT-0001, ...), and the
same corpus always yields the same draft file apart from the
`drafted_on` date stamp the caller may pin with --date.

    python3 scripts/wiki_eval_draft.py draft PAGE [PAGE ...]
        [--out staging/eval-drafts/<name>.jsonl] [--date YYYY-MM-DD]
    python3 scripts/wiki_eval_draft.py draft --all
        [--out ...] [--date ...]

Exit codes: 0 ok · 4 boundary refusal · 2 usage error.
Stdlib only. Importable in-process (tests drive the functions
against fixture roots).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_REL = Path("staging") / "eval-drafts"
GOLDEN_REL = Path("evaluation") / "golden-questions.jsonl"

CITE_RE = re.compile(r"\^\[cite:\s*([^\]#\s]+)#L(\d+)(?:-L?(\d+))?\s*\]")
CITE_LOOSE_RE = re.compile(r"\^\[cite:[^\]]*\]")
# A sentence in our idiom may end ".^[cite: ...]" — the marker
# sits between the full stop and the next sentence, so splitting
# must keep the marker attached to ITS sentence.
SENT_END_RE = re.compile(r"[.!?](?:\^\[cite:[^\]]*\])?\s+")


def split_sentences(text: str):
    parts, start = [], 0
    for mm in SENT_END_RE.finditer(text):
        parts.append(text[start:mm.end()].strip())
        start = mm.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]
HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")


class DraftError(Exception):
    """A boundary refusal (exit 4)."""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                                      s.lower())).strip()


def sha256_file(path: Path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_frontmatter(text: str):
    """(fields dict of simple scalars/lists, body). Mirrors the
    small parsers elsewhere in scripts/ (no YAML dependency)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm, key = {}, None
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip("'\"") for v in
                           val[1:-1].split(",") if v.strip()]
            elif val:
                fm[key] = val.strip("'\"")
            else:
                fm[key] = []
        elif key and line.strip().startswith("- "):
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(line.strip()[2:].strip().strip("'\""))
    return fm, text[end + 4:]


def clean(sentence: str) -> str:
    s = CITE_LOOSE_RE.sub("", sentence)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`>]+", "", s)
    return " ".join(s.split()).strip()


def body_sentences(body: str):
    """Yield (sentence, cite_target_or_None) in page order.
    Fenced code, headings, tables and callout markers are not
    prose sentences. A sentence is citation-bearing when it
    carries a ^[cite:] marker; the marker is stripped from the
    returned sentence and its target returned alongside."""
    text = re.sub(r"```.*?```", "", body, flags=re.S)
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if lines[0].startswith(("#", "|", "> [!")):
            continue
        joined = " ".join(re.sub(r"^>\s?", "", ln) for ln in lines)
        joined = re.sub(r"^[-*]\s+", "", joined)
        for sent in split_sentences(joined):
            sent = sent.strip()
            if len(sent) < 40:
                continue
            m = CITE_RE.search(sent)
            cite = None
            if m:
                cite = {"source": m.group(1),
                        "start": int(m.group(2)),
                        "end": int(m.group(3)) if m.group(3)
                        else int(m.group(2))}
            out.append((clean(sent), cite))
    return out


def headings_of(body: str):
    return [m.group(1).strip() for ln in body.splitlines()
            if (m := HEADING_RE.match(ln.strip()))]


def draft_from_page(root: Path, rel_page: str, start_id: int):
    """Draft candidates from one compiled page. Returns
    (records, next_id). A candidate is drafted only when its
    expected answer occurs verbatim (normalised) in the page —
    the RAGET answerability check, deterministically."""
    text = (root / rel_page).read_text(encoding="utf-8",
                                       errors="ignore")
    fields, body = parse_frontmatter(text)
    title = fields.get("title") or Path(rel_page).stem
    page_norm = norm(clean(body))
    records, n = [], start_id

    def add(question, answer, kind, cite):
        nonlocal n
        if norm(answer) not in page_norm:
            return  # unanswerable from this page: never drafted
        n += 1
        records.append({
            "id": f"DRAFT-{n:04d}",
            "status": "draft",
            "approved": False,
            "origin": "wiki_eval_draft",
            "kind": kind,
            "question": question,
            "expected_answer": answer,
            "must_cite": [rel_page],
            "cite": cite,
            "source_page": rel_page,
        })

    claim = fields.get("claim")
    if isinstance(claim, str) and len(claim) >= 25:
        add(f"According to {title}, is the following claim "
            f"supported: {claim}", claim, "claim-check", None)
    for sent, cite in body_sentences(body):
        if cite is None:
            continue  # drafts rest on citation-bearing claims
        topic = sent.split(":")[0][:70].strip()
        add(f"What does {title} state about: {topic}?",
            sent, "citation-recall", cite)
    for head in headings_of(body):
        if head.lower() in (title or "").lower():
            continue
        # Heading questions are answerable only when the page
        # body states the heading's own terms in a full sentence;
        # the expected answer is that sentence, found by search.
        for sent, cite in body_sentences(body):
            if norm(head).split() and all(
                    t in norm(sent) for t in norm(head).split()
                    if len(t) > 2):
                add(f"According to {title}, what is covered "
                    f"under '{head}'?", sent, "section-recall", cite)
                break
    return records, n


def check_out_boundary(root: Path, out: Path) -> Path:
    """Enforce the staging boundary; returns the resolved out
    path or raises DraftError. This is the ONLY gate a write
    passes through, and cmd_draft calls it before any drafting
    work touches disk."""
    staging = (root / STAGING_REL).resolve()
    resolved = out if out.is_absolute() else (root / out)
    resolved = resolved.resolve()
    if "golden-questions" in resolved.name:
        raise DraftError(
            "refused: a draft may never be named for, or written "
            "over, a golden set (golden-questions)")
    try:
        resolved.relative_to(staging)
    except ValueError:
        raise DraftError(
            f"refused: drafts live only under {STAGING_REL}/ "
            f"(got {out}); evaluation/ is owner-promotion "
            "territory this tool never writes to")
    if resolved.exists():
        raise DraftError(
            f"refused: {out} already exists — drafts are new "
            "files, never overwrites")
    if resolved.suffix != ".jsonl":
        raise DraftError("refused: a draft file is .jsonl")
    return resolved


def cmd_draft(root: Path, pages, out: Path, drafted_on: str):
    resolved = check_out_boundary(root, out)
    golden_before = sha256_file(root / GOLDEN_REL)
    records, n = [], 0
    for rel in pages:
        recs, n = draft_from_page(root, rel, n)
        records.extend(recs)
    for rec in records:
        rec["drafted_on"] = drafted_on
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                + "\n" for r in records), encoding="utf-8")
    golden_after = sha256_file(root / GOLDEN_REL)
    report = {"written": str(resolved), "drafts": len(records),
              "pages": len(pages), "all_unapproved":
              all(r["approved"] is False and r["status"] == "draft"
                  for r in records),
              "golden_sha256_before": golden_before,
              "golden_sha256_after": golden_after,
              "golden_untouched": golden_before == golden_after}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if golden_before == golden_after else 5


def all_pages(root: Path):
    wiki = root / "wiki"
    out = []
    for p in sorted(wiki.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel in ("wiki/index.md", "wiki/log.md"):
            continue
        if any(part in ("filings", "talk", "access")
               for part in Path(rel).parts[1:-1]):
            continue
        out.append(rel)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    pd = sub.add_parser("draft", help="draft questions from pages")
    pd.add_argument("pages", nargs="*",
                    help="repo-relative wiki pages")
    pd.add_argument("--all", action="store_true",
                    help="draft from every compiled page")
    pd.add_argument("--out", required=True,
                    help="NEW file under staging/eval-drafts/")
    pd.add_argument("--date", default=None,
                    help="drafted_on stamp (default: today)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "draft":
        pages = all_pages(root) if args.all else list(args.pages)
        if not pages:
            print("refused: name at least one page or pass --all",
                  file=sys.stderr)
            return 2
        for rel in pages:
            if not (root / rel).is_file():
                print(f"no such page: {rel}", file=sys.stderr)
                return 2
        try:
            return cmd_draft(root, pages, Path(args.out),
                             args.date or str(date.today()))
        except DraftError as exc:
            print(str(exc), file=sys.stderr)
            return 4
    return 2


if __name__ == "__main__":
    sys.exit(main())
