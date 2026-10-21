#!/usr/bin/env python3
"""wiki_memory_transparency.py — memory-transparency views over the
wiki's EXISTING records (Marathon R4, lane A, item 1).

Pattern: Sakana Chat's "My Fish" memory view (proprietary — IDEA
ONLY; this is an independent re-implementation in our own code,
stdlib only, no model calls).

Reads only records that already exist:
  - evaluation/claim-index.jsonl   (the claims list; append-only,
    one record per claim page per index run — the latest record
    per claim_id is the claim's current form)
  - wiki/access/qa-2026.jsonl      (the Ask door's Q&A log; each
    record's citations are the pages that answer used — the
    retrieval-event log)
  - evaluation/notices.jsonl       (notice applications /
    retirements naming a page, when present)
  - evaluation/outcomes.jsonl      (claim outcomes, when present)
  - evaluation/reverify-history.jsonl (per-claim re-verification
    events, when present)
  - the wiki pages themselves, scanned for [[wikilinks]] so a
    claim's connections name the pages that cite it in prose.

Produces evaluation/memory-transparency.json with four views:
  claims        — latest record per claim, sorted by claim_id
  claim_history — {claim_id: [event, ...]}: every derivable event
                  (indexed snapshots, notices, outcomes,
                  re-verifications), in file order per source
  connections   — per claim: its page, the pages that cite/link
                  it, the Ask events grounded in it, and its
                  supports/contradicts counts from the index
  ask_events    — each Q&A record with the pages it used
                  (citations resolved to page paths) and the
                  claims it is grounded in (cited pages that are
                  claim pages in the claim index)

Usage:
  python3 scripts/wiki_memory_transparency.py [--root DIR]
      [--out FILE]            build (default) and write the JSON
  python3 scripts/wiki_memory_transparency.py [--root DIR] check
      rebuild in memory and compare with the file on disk
      (exit 0 = identical, 1 = differs or missing)
Stdlib only. Deterministic: no timestamps are generated; the
output depends only on the records read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def read_jsonl(path):
    """JSONL records from path; [] when the file is absent.
    Non-object / unparseable lines are skipped (they are not
    records this view can show)."""
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def page_key_map(page_paths):
    """Map every key a citation might use to its page path:
    the full path, the path without .md, the path without the
    leading wiki/ and .md, and the bare stem. First page (in
    sorted order) wins a contested key, so resolution is
    deterministic."""
    key_map = {}
    for path in sorted(page_paths):
        stem = Path(path).stem
        no_ext = path[:-3] if path.endswith(".md") else path
        bare = no_ext[len("wiki/"):] if no_ext.startswith("wiki/") else no_ext
        for key in (path, no_ext, bare, stem):
            key_map.setdefault(key, path)
    return key_map


def citation_text(citation):
    """A QA citation may be a string or an object carrying an
    id / page_id / page field; anything else yields ''."""
    if isinstance(citation, str):
        return citation.strip()
    if isinstance(citation, dict):
        for field in ("id", "page_id", "page", "path"):
            value = citation.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def resolve_citation(citation, key_map):
    """Resolve one citation to a page path, or None."""
    text = citation_text(citation)
    if not text:
        return None
    return key_map.get(text) or key_map.get(Path(text).stem)


def grounded_claims(citations, claim_ids, key_map):
    """The grounded-in computation, shared in spirit with the
    Lens (lenslib.grounded_claims mirrors it): resolve every
    citation to a page; the answer is grounded in exactly the
    cited pages that are claim pages in the claim index.
    Returns (cited_pages, grounded_claim_ids), both sorted."""
    cited = sorted({p for p in
                    (resolve_citation(c, key_map) for c in citations or [])
                    if p})
    grounded = [p for p in cited if p in claim_ids]
    return cited, grounded


def wiki_page_paths(root):
    wiki = Path(root) / "wiki"
    if not wiki.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix()
                  for p in wiki.rglob("*.md") if p.is_file())


def citing_pages(root, page_paths, key_map, claim_ids):
    """{claim_page_path: [pages whose wikilinks resolve to it]}.
    A page does not count as citing itself."""
    cited_by = defaultdict(set)
    wiki = Path(root) / "wiki"
    for rel in page_paths:
        try:
            text = (wiki.parent / rel).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in WIKILINK_RE.findall(text):
            resolved = key_map.get(target.strip()) or \
                key_map.get(Path(target.strip()).stem)
            if resolved in claim_ids and resolved != rel:
                cited_by[resolved].add(rel)
    return {k: sorted(v) for k, v in cited_by.items()}


def build_transparency(root):
    root = Path(root)
    claim_rows = read_jsonl(root / "evaluation" / "claim-index.jsonl")
    latest = {}
    for row in claim_rows:
        cid = row.get("claim_id")
        if isinstance(cid, str) and cid:
            latest[cid] = row
    claim_ids = set(latest)
    claims = [latest[cid] for cid in sorted(latest)]

    page_paths = wiki_page_paths(root)
    key_map = page_key_map(page_paths + sorted(claim_ids))

    # ---- Ask events (the retrieval-event log) ----
    qa_rows = read_jsonl(root / "wiki" / "access" / "qa-2026.jsonl")
    ask_events = []
    ask_by_claim = defaultdict(list)
    for rec in qa_rows:
        citations = rec.get("citations") or []
        cited_pages, grounded = grounded_claims(citations, claim_ids, key_map)
        event = {
            "id": rec.get("id"),
            "question": rec.get("question"),
            "asker": rec.get("asker"),
            "asked_at": rec.get("asked_at"),
            "answered_at": rec.get("answered_at"),
            "status": rec.get("status"),
            "mode": rec.get("mode"),
            "citations": citations,
            "cited_pages": cited_pages,
            "grounded_claims": len(grounded),
            "grounded_claim_ids": grounded,
        }
        ask_events.append(event)
        for cid in grounded:
            if event["id"]:
                ask_by_claim[cid].append(event["id"])

    # ---- Claim history: every event the records carry ----
    history = defaultdict(list)
    for row in claim_rows:
        cid = row.get("claim_id")
        if cid in claim_ids:
            history[cid].append({
                "event": "indexed", "date": row.get("indexed_on"),
                "stated": row.get("stated"), "hash": row.get("hash"),
                "supports": row.get("supports"),
                "contradicts": row.get("contradicts"),
                "verified_n": row.get("verified_n"),
                "superseded": row.get("superseded"),
            })
    for rec in read_jsonl(root / "evaluation" / "notices.jsonl"):
        page = rec.get("page")
        if page in claim_ids and rec.get("kind") in ("applied", "retired"):
            history[page].append({
                "event": f"notice-{rec['kind']}",
                "date": rec.get("date") or rec.get("created"),
                "notice": rec.get("notice"), "by": rec.get("by"),
                "reason": rec.get("reason"),
            })
    for rec in read_jsonl(root / "evaluation" / "outcomes.jsonl"):
        page = rec.get("claim") or rec.get("page")
        if page in claim_ids:
            history[page].append({
                "event": "outcome",
                "date": rec.get("date") or rec.get("as_of"),
                "outcome": rec.get("outcome"), "by": rec.get("by"),
            })
    for rec in read_jsonl(root / "evaluation" / "reverify-history.jsonl"):
        page = rec.get("claim") or rec.get("page")
        if page in claim_ids:
            history[page].append({
                "event": "reverified",
                "date": rec.get("date") or rec.get("checked_on")
                        or rec.get("as_of"),
                "result": rec.get("result") or rec.get("outcome"),
                "by": rec.get("by"),
            })

    # ---- Connections: claim -> pages that cite/support it ----
    cited_by = citing_pages(root, page_paths, key_map, claim_ids)
    connections = []
    for cid in sorted(claim_ids):
        row = latest[cid]
        connections.append({
            "claim_id": cid,
            "page": cid,
            "cited_by_pages": cited_by.get(cid, []),
            "ask_event_ids": sorted(set(ask_by_claim.get(cid, []))),
            "supports": row.get("supports"),
            "contradicts": row.get("contradicts"),
        })

    return {
        "kind": "memory-transparency",
        "version": 1,
        "sources": {
            "claim_index_records": len(claim_rows),
            "claims": len(claims),
            "ask_records": len(qa_rows),
            "wiki_pages_scanned": len(page_paths),
        },
        "claims": claims,
        "claim_history": {cid: history[cid] for cid in sorted(history)},
        "connections": connections,
        "ask_events": ask_events,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default=None,
                    help="output path (default: <root>/evaluation/"
                         "memory-transparency.json)")
    ap.add_argument("cmd", nargs="?", default="build",
                    choices=("build", "check"))
    args = ap.parse_args(argv)
    root = Path(args.root)
    out = Path(args.out) if args.out else \
        root / "evaluation" / "memory-transparency.json"
    data = build_transparency(root)
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if args.cmd == "check":
        current = out.read_text(encoding="utf-8") if out.is_file() else None
        ok = current == text
        print(json.dumps({"check": "pass" if ok else "fail",
                          "claims": len(data["claims"]),
                          "ask_events": len(data["ask_events"])}))
        return 0 if ok else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"written": str(out), "claims": len(data["claims"]),
                      "connections": len(data["connections"]),
                      "ask_events": len(data["ask_events"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
