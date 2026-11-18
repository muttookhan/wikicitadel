#!/usr/bin/env python3
"""Low-confidence web expansion hook (SearXNG pattern, scoped form).

Implements Marathon Round 3 TB8 row 4, from the SearXNG find in
raw/sources/2026-10-20-global-landscape/r2-europe-india-academic-finds.md:
a self-hosted metasearch layer as the web-expansion step when
internal retrieval confidence is low. SearXNG is AGPL-3.0 —
IDEA ONLY: no code copied, nothing of it embedded or called. This
is our own hook shaped like the pattern.

The discipline, pinned by tests:

  * The hook takes a CONFIDENCE VALUE AS INPUT (a float in
    [0, 1], supplied by whoever scored the retrieval). It does
    not import, call, or depend on any other lane's scorer.
  * At or above the threshold (default 0.5) nothing happens:
    no proposals, no fetch, no files.
  * Below the threshold the hook PROPOSES expansion queries
    (deterministic, stated rules). Proposing is always safe.
  * Fetching is an INJECTABLE SEAM and DEFAULT OFF: without an
    explicitly enabled flag AND an injected fetcher callable,
    no web call is made — the CLI ships with no fetcher wired
    at all, so the CLI can propose but never fetch.
  * Fetched results land as UNFILED candidate sources: one
    Markdown file per result under the stated out dir
    (default staging/web-candidates/), each carrying provenance
    (origin URL, query, confidence, fetched-at, via) and
    `status: unfiled` / `compiled: false`. They are NEVER
    written into wiki/ and NEVER auto-compiled — a human ingest
    act is the only way a candidate becomes a source.

Usage:
  python3 scripts/wiki_web_expand.py "some query" --confidence 0.31
  (proposes only; fetching requires a programmatic fetcher —
   see run_expansion — deliberately not wired into the CLI)

Exit codes: 0 = ok (expanded or not needed); 2 = usage error.
Stdlib only; no network code exists in this file.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLD = 0.5
DEFAULT_OUT = "staging/web-candidates"


def propose_queries(query):
    """Deterministic expansion proposals for one query: the
    query itself, a quoted exact-phrase form (when multiword),
    and an overview-seeking form. Stated rules, no model."""
    q = " ".join(str(query).split())
    proposals = [q]
    if " " in q:
        proposals.append(f'"{q}"')
    proposals.append(f"{q} overview")
    seen, out = set(), []
    for p in proposals:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _slug(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (s[:limit].strip("-") or "candidate")


def candidate_markdown(result, *, query, confidence, fetched_at):
    title = str(result.get("title") or result.get("url") or "untitled")
    url = str(result.get("url") or "")
    snippet = str(result.get("snippet") or "")
    return (
        "---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        "status: unfiled\n"
        "compiled: false\n"
        "via: web-expansion (SearXNG pattern; injectable fetcher)\n"
        f"origin_url: {url}\n"
        f"query: \"{query.replace(chr(34), chr(39))}\"\n"
        f"retrieval_confidence: {confidence}\n"
        f"fetched_at: {fetched_at}\n"
        "---\n\n"
        f"# UNFILED candidate — {title}\n\n"
        "This file is a candidate source proposed by the "
        "low-confidence web-expansion hook. It has NOT been "
        "ingested, verified, or compiled into the wiki. A human "
        "ingest act is required before anything here is relied "
        "on.\n\n"
        f"Origin: {url}\n\n"
        f"{snippet}\n"
    )


def run_expansion(query, confidence, *, threshold=DEFAULT_THRESHOLD,
                  enabled=False, fetcher=None, out_dir=None,
                  root=ROOT, now=None):
    """The hook. Returns a report dict; writes candidate files
    only when enabled AND a fetcher is injected AND confidence
    is below threshold."""
    if not (0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidence must be in [0, 1]")
    confidence = float(confidence)
    report = {"query": query, "confidence": confidence,
              "threshold": threshold, "expanded": False,
              "reason": None, "proposed_queries": [],
              "fetched": False, "candidates": []}
    if confidence >= threshold:
        report["reason"] = ("confidence at or above threshold — "
                            "no expansion proposed")
        return report
    report["expanded"] = True
    report["proposed_queries"] = propose_queries(query)
    if not enabled:
        report["reason"] = ("low confidence; expansion proposed "
                            "but fetching is DEFAULT OFF "
                            "(enabled=False)")
        return report
    if fetcher is None:
        report["reason"] = ("low confidence; expansion enabled "
                            "but no fetcher injected — no web "
                            "call made (seam unwired)")
        return report
    out = Path(out_dir) if out_dir else Path(root) / DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    fetched_at = (now or datetime.now(timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    for pq in report["proposed_queries"][:1]:  # first proposal only
        for result in fetcher(pq):
            url = str(result.get("url") or "")
            digest = hashlib.sha256(url.encode()).hexdigest()[:10]
            name = f"{_slug(result.get('title') or url)}-{digest}.md"
            path = out / name
            path.write_text(
                candidate_markdown(result, query=pq,
                                   confidence=confidence,
                                   fetched_at=fetched_at),
                encoding="utf-8")
            report["candidates"].append(
                {"path": str(path), "origin_url": url,
                 "status": "unfiled", "compiled": False})
    report["fetched"] = True
    report["reason"] = ("low confidence; fetched via injected "
                        "fetcher; candidates filed as UNFILED "
                        "only — never auto-compiled")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--confidence", type=float, required=True,
                    help="retrieval confidence in [0, 1], supplied "
                         "by the caller (this hook scores nothing)")
    ap.add_argument("--threshold", type=float,
                    default=DEFAULT_THRESHOLD)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    try:
        report = run_expansion(
            args.query, args.confidence, threshold=args.threshold,
            enabled=False, fetcher=None, out_dir=args.out_dir,
            root=args.root)
    except ValueError as exc:
        print(f"web-expand: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
