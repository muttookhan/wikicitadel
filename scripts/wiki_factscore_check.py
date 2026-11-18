#!/usr/bin/env python3
"""wiki_factscore_check.py — FActScore atomic-claim compilation
check (Marathon R5 lane BB).

Pattern: Min et al., "FActScore: Fine-grained Atomic Evaluation
of Factual Precision in Long Form Text Generation" — a compiled
text is decomposed into atomic claims and each claim is verified
against its source. Re-implemented deterministically in our own
code: NO model calls anywhere.

How this differs from scripts/wiki_factcheck.py (which it does
not replace): factcheck scores a whole page's sentences against
the page's frontmatter sources as one bag of words. This checker
works PER CLAIM at the citation the claim itself carries, in
the wiki's own idiom:

  Decomposition (deterministic):
    * the frontmatter `claim:` sentence, when present, is one
      atomic claim (kind: frontmatter-claim);
    * each body sentence carrying a ^[cite: path#L<a>-L<b>]
      marker is one atomic claim (kind: cited-sentence), grouped
      under the nearest preceding heading;
    * each other declarative body sentence of substance is one
      atomic claim with NO citation (kind: uncited-sentence) —
      it is reported, never silently dropped.

  Verification (per claim, at the level our machinery allows):
    * no marker            -> verdict `missing-citation`;
    * marker target absent -> verdict `citation-unresolvable`;
    * range out of bounds  -> verdict `citation-out-of-range`;
    * otherwise the cited lines are read (the same lines the
      cite-lock machinery locks: scripts/wiki_cite_lock.py's
      line-range semantics) and the claim's content-token
      overlap with the cited passage is computed:
        overlap >= threshold -> `supported`
        overlap <  threshold -> `unsupported`
      with the overlap and the cited passage's first line
      recorded on the verdict, so a human can re-check in one
      glance. Lexical support is a weaker instrument than a
      model judge and the report says so on its face.

NO-AUTO-VERIFY BOUNDARY (enforced in code): this tool is
REPORT-ONLY. It never edits the checked page, never writes
`verified_until` / `verified_by` / `status` / `confidence`
(anywhere — its only optional write is the report file named
by --out, and --out equal to a checked page is refused), and
every report carries "auto_verified": false and
"page_status_changed": false. A page is marked verified by
the owner attestation machinery or not at all; the checker
reports, humans/records decide.

    python3 scripts/wiki_factscore_check.py [--root DIR]
        [--threshold 0.35] [--out REPORT.json]
        check PAGE [PAGE ...]

Exit codes: 0 = every claim supported · 1 = at least one
claim not supported (a finding, not a crash) · 2 usage error ·
4 = refused write (report path collides with a checked page).
Stdlib only. Importable in-process (tests drive the functions
against fixture roots).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""the a an and or of to in is are was were be been being
for on with as by at from this that it its has have had not no do does
did will would can could should may might must shall than then so such
into over under more most other some any only also just very he she we
they you i his her their our your my who whom which what when where why
how all each both few many much own same don now""".split())
DEFAULT_THRESHOLD = 0.35
VERDICTS = ("supported", "unsupported", "missing-citation",
            "citation-unresolvable", "citation-out-of-range")


def parse_frontmatter(text: str):
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


def content_tokens(text: str):
    return {t for t in TOKEN_RE.findall(text.lower())
            if t not in STOPWORDS and len(t) >= 3}


def clean(sentence: str) -> str:
    s = CITE_LOOSE_RE.sub("", sentence)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`>]+", "", s)
    return " ".join(s.split()).strip()


def decompose(text: str):
    """Atomic claims of one page, in page order:
    [{claim, kind, heading, cite}] where cite is
    {source, start, end} or None."""
    fields, body = parse_frontmatter(text)
    claims = []
    claim = fields.get("claim")
    if isinstance(claim, str) and len(claim) >= 15:
        claims.append({"claim": claim, "kind": "frontmatter-claim",
                       "heading": None, "cite": None})
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    heading = None
    for block in re.split(r"\n\s*\n", body):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        hm = HEADING_RE.match(lines[0].strip())
        if hm:
            heading = hm.group(2).strip()
            lines = lines[1:]
            if not lines:
                continue
        first = lines[0].strip()
        if first.startswith(("|", "> [!")) or first.startswith("---"):
            continue
        joined = " ".join(re.sub(r"^>\s?", "", ln.strip())
                          for ln in lines)
        joined = re.sub(r"^[-*]\s+", "", joined)
        for sent in split_sentences(joined):
            raw = sent.strip()
            if len(raw) < 25 or len(content_tokens(clean(raw))) < 3:
                continue
            m = CITE_RE.search(raw)
            cite = None
            if m:
                cite = {"source": m.group(1),
                        "start": int(m.group(2)),
                        "end": int(m.group(3)) if m.group(3)
                        else int(m.group(2))}
            claims.append({
                "claim": clean(raw),
                "kind": "cited-sentence" if cite else
                        "uncited-sentence",
                "heading": heading, "cite": cite})
    return claims


def verify_claim(root: Path, claim: dict, threshold: float) -> dict:
    """One per-claim verdict. Pure: reads the cited source,
    writes nothing, decides nothing about the page."""
    out = {"claim": claim["claim"][:300], "kind": claim["kind"],
           "heading": claim["heading"], "cite": claim["cite"]}
    cite = claim["cite"]
    if claim["kind"] == "frontmatter-claim":
        out.update(verdict="missing-citation",
                   detail="frontmatter claim carries no inline "
                          "marker; its support is the page's "
                          "sources list, checked by other lanes")
        return out
    if cite is None:
        out.update(verdict="missing-citation",
                   detail="sentence carries no ^[cite:] marker")
        return out
    src = root / cite["source"]
    if not src.is_file():
        out.update(verdict="citation-unresolvable",
                   detail=f"cited file not on disk: {cite['source']}")
        return out
    lines = src.read_text(encoding="utf-8",
                          errors="ignore").splitlines()
    if cite["start"] < 1 or cite["end"] > len(lines) \
            or cite["end"] < cite["start"]:
        out.update(verdict="citation-out-of-range",
                   detail=f"cited L{cite['start']}-L{cite['end']} "
                          f"outside the file's {len(lines)} lines")
        return out
    passage = "\n".join(lines[cite["start"] - 1:cite["end"]])
    toks = content_tokens(claim["claim"])
    overlap = (len(toks & content_tokens(passage)) / len(toks)
               if toks else 0.0)
    out.update(
        verdict="supported" if overlap >= threshold else "unsupported",
        overlap=round(overlap, 3),
        detail=("cited passage shares enough of the claim's "
                "content vocabulary" if overlap >= threshold else
                "cited passage does not share enough of the "
                "claim's content vocabulary — the citation is "
                "present but does not support the claim at the "
                "lexical level this checker can see"),
        cited_excerpt=passage.splitlines()[0][:160] if passage else "")
    return out


def check_page(root: Path, rel_page: str,
               threshold: float = DEFAULT_THRESHOLD) -> dict:
    text = (root / rel_page).read_text(encoding="utf-8",
                                       errors="ignore")
    verdicts = [verify_claim(root, c, threshold)
                for c in decompose(text)]
    counts = {v: sum(1 for r in verdicts if r["verdict"] == v)
              for v in VERDICTS}
    return {"page": rel_page, "claims": len(verdicts),
            "counts": counts, "verdicts": verdicts,
            "auto_verified": False, "page_status_changed": False}


def run(root: Path, pages, threshold: float) -> dict:
    records = [check_page(root, rel, threshold) for rel in pages]
    totals = {v: sum(r["counts"][v] for r in records)
              for v in VERDICTS}
    return {
        "tool": "scripts/wiki_factscore_check.py",
        "kind": "factscore-atomic-claim-report",
        "pattern": "Min et al. FActScore atomic-claim "
                   "decomposition — deterministic, lexical "
                   "verification at each claim's own citation; "
                   "report-only, never auto-verifies a page",
        "date": str(date.today()),
        "threshold": threshold,
        "auto_verified": False,
        "page_status_changed": False,
        "summary": {"pages": len(records),
                    "claims": sum(r["claims"] for r in records),
                    "by_verdict": totals},
        "records": records,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--threshold", type=float,
                    default=DEFAULT_THRESHOLD)
    ap.add_argument("--out", default=None,
                    help="write the JSON report here (never a "
                         "checked page)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check")
    pc.add_argument("pages", nargs="+",
                    help="repo-relative wiki pages")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    for rel in args.pages:
        if not (root / rel).is_file():
            print(f"no such page: {rel}", file=sys.stderr)
            return 2
    if args.out:
        out = Path(args.out)
        resolved = out if out.is_absolute() else root / out
        if resolved.resolve() in {(root / rel).resolve()
                                  for rel in args.pages}:
            print("refused: the report may not overwrite a "
                  "checked page — this checker never edits a "
                  "page", file=sys.stderr)
            return 4
    report = run(root, list(args.pages), args.threshold)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        target = out if out.is_absolute() else root / out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    bad = sum(v for k, v in report["summary"]["by_verdict"].items()
              if k != "supported")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
