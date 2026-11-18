#!/usr/bin/env python3
"""Answer-key audit (Marathon R2 lane B2) — REPORT ONLY.

One pass over the golden + extended sets (plus the conflict slice
when present). For each question, the audit checks the set's OWN
recorded expectations against the live corpus:

  1. every cited page (must_cite + acceptable_cites) still exists;
  2. the expected key terms still appear in the cited pages' text.

Key terms are the set's own: `key_facts` when the question carries
them. Golden questions carry no key_facts, so for those the salient
terms of `expected_answer` are derived deterministically — dates,
numbers, ALL-CAPS tokens and quoted phrases. Abstention questions
(expected_abstain, no citations, no key terms) have no key to
check: they are reported ok with that reason stated, not silently
skipped.

Verdicts: `ok` or `suspect`, each with a reason (the missing pages
or the missing terms, named). A suspect verdict is a FINDING for a
human to disposition — a term can move house legitimately, and a
golden expectation can itself be the stale artefact. This tool
NEVER edits a question set: it reads sets and wiki pages and
writes only its report (stdout, or the --out file).

Matching is normalised (case folded, whitespace collapsed,
markdown emphasis stripped) with an alphanumeric-squash fallback,
so "$44/hr" and "3,335" match their plain-text forms; a term that
matches in neither form is missing.

Usage:
  python3 scripts/wiki_answer_key_audit.py [--root DIR]
          [--sets FILE ...] [--out FILE]
Defaults: golden + extended (+ conflict when present) under
<root>/evaluation/, report to stdout. Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETS = ("golden-questions.jsonl", "extended-questions.jsonl",
                "conflict-questions.jsonl")


def load_questions(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    return [r for r in rows if r.get("kind") != "header"]


def _norm(text):
    text = text.lower()
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text)


def _squash(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def term_present(term, page_text_norm, page_text_squash):
    return _norm(term) in page_text_norm or _squash(term) in page_text_squash


def derive_terms(expected_answer):
    """Salient terms of an expected_answer, deterministic order:
    quoted phrases, dates, numbers, ALL-CAPS tokens (deduped)."""
    terms = []
    for m in re.findall(r'"([^"]{3,})"', expected_answer or ""):
        terms.append(m)
    for m in re.findall(r"\b20\d\d-\d\d-\d\d\b", expected_answer or ""):
        terms.append(m)
    for m in re.findall(r"\b\d[\d,]*\b", expected_answer or ""):
        if m not in terms:
            terms.append(m)
    for m in re.findall(r"\b[A-Z]{2,}(?:-[A-Z]+)?\b", expected_answer or ""):
        if m not in terms:
            terms.append(m)
    return terms


def audit_question(q, root):
    """Audit one question dict against the corpus under root."""
    root = Path(root)
    qid = q.get("id", "?")
    pages = list(q.get("must_cite") or []) + list(q.get("acceptable_cites") or [])
    missing_pages = [p for p in pages if not (root / p).exists()]
    if q.get("expected_abstain") and not pages and not q.get("key_facts"):
        if missing_pages:
            return {"id": qid, "verdict": "suspect",
                    "reason": f"cited page(s) missing: {', '.join(missing_pages)}",
                    "missing_pages": missing_pages, "missing_terms": []}
        return {"id": qid, "verdict": "ok",
                "reason": "abstention question — no cited pages or key terms to check",
                "missing_pages": [], "missing_terms": []}
    text = ""
    for p in pages:
        f = root / p
        if f.exists():
            text += f.read_text(encoding="utf-8", errors="ignore") + "\n"
    norm, squash = _norm(text), _squash(text)
    terms = list(q.get("key_facts") or []) or derive_terms(q.get("expected_answer", ""))
    missing_terms = [t for t in terms if not term_present(t, norm, squash)]
    reasons = []
    if missing_pages:
        reasons.append(f"cited page(s) missing: {', '.join(missing_pages)}")
    if missing_terms:
        reasons.append(f"key term(s) not in cited pages: {', '.join(missing_terms)}")
    if reasons:
        return {"id": qid, "verdict": "suspect", "reason": "; ".join(reasons),
                "missing_pages": missing_pages, "missing_terms": missing_terms}
    if not terms:
        return {"id": qid, "verdict": "ok",
                "reason": "cited pages exist; no key terms recorded or derivable",
                "missing_pages": [], "missing_terms": []}
    return {"id": qid, "verdict": "ok",
            "reason": f"all {len(pages)} cited page(s) exist; all "
                      f"{len(terms)} key term(s) present",
            "missing_pages": [], "missing_terms": []}


def audit_sets(root, set_paths):
    """Audit every question in the given set files, in file order."""
    findings = []
    for sp in set_paths:
        for q in load_questions(sp):
            row = audit_question(q, root)
            row["set"] = Path(sp).name
            findings.append(row)
    return findings


def render_report(findings):
    ok = sum(1 for f in findings if f["verdict"] == "ok")
    lines = [
        "# Answer-key audit — report only",
        "",
        f"Questions audited: {len(findings)} — ok: {ok}, "
        f"suspect: {len(findings) - ok}. This report never edits a "
        "key; a suspect verdict is a finding for a human to "
        "disposition.",
        "",
        "| set | question | verdict | reason |",
        "|---|---|---|---|",
    ]
    for f in findings:
        reason = f["reason"].replace("|", "/")
        lines.append(f"| {f['set']} | {f['id']} | {f['verdict']} | {reason} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT),
                    help="tree root holding wiki/ and evaluation/")
    ap.add_argument("--sets", nargs="*", default=None,
                    help="question-set files (default: golden + "
                         "extended + conflict under <root>/evaluation/)")
    ap.add_argument("--out", default=None,
                    help="write the report here (default: stdout)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.sets:
        set_paths = [Path(s) for s in args.sets]
    else:
        set_paths = [root / "evaluation" / name for name in DEFAULT_SETS
                     if (root / "evaluation" / name).exists()]
    findings = audit_sets(root, set_paths)
    report = render_report(findings)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"audited {len(findings)} questions; wrote {args.out}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
