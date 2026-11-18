#!/usr/bin/env python3
"""Crossref-gated correction acceptance (Marathon R3,
Tier B row TB3-4; CiteIndex pattern).

Pattern: CiteIndex (MIT, re-verified in the 2026-10-19
survey) — a correction to a claim that rests on a scholarly
source is accepted only when its citation actually
resolves. Re-implemented from the idea; no code copied.

A correction record is a JSON object:

    {"claim": "the claim as it stands",
     "correction": "the corrected statement",
     "citation": {"doi": "10.1000/example.1",
                  "quote": "the supporting quote",
                  "locator": "p. 4, para. 2"}}

THE GATE: when a correction carries a scholarly citation
(a DOI, or a `ref` naming a registered source), it is
accepted into the corrections flow only when the citation
resolves in the scholarly register,
evaluation/scholarly-register.jsonl (one JSON line per
registered source: {"doi": ..., "title": ...} and/or
{"ref": ..., "title": ...}), AND the citation carries both
a supporting quote and a stable locator. A correction with
no scholarly citation is not gated here (verdict
"not-scholarly") — it follows the ordinary corrections
flow. An unresolvable citation is REJECTED, never queued
silently.

THE CROSSREF SEAM: live Crossref lookup is an injectable
resolver, OFF by default (no network in the gate, none in
tests). A caller may pass a resolver object with
`resolve(doi) -> dict | None`; only when it resolves AND
the offline register also holds the source does the gate
accept — the register stays the authority, Crossref is a
discovery aid whose hits must be registered on the record
before they can gate anything.

Usage:
  python3 scripts/wiki_correction_gate.py check CORRECTION.json
  python3 scripts/wiki_correction_gate.py register SOURCE.json

Exit codes: check 0 = accepted (or not-scholarly), 1 =
rejected by the gate, 2 = usage error. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/scholarly-register.jsonl"


def load_register(root: Path):
    path = root / REGISTER_REL
    by_doi, by_ref = {}, {}
    if path.is_file():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            rec = json.loads(ln)
            if rec.get("doi"):
                by_doi[rec["doi"].lower()] = rec
            if rec.get("ref"):
                by_ref[rec["ref"]] = rec
    return by_doi, by_ref


def gate(root: Path, correction: dict, resolver=None):
    """(verdict, reasons). verdict in accepted | rejected |
    not-scholarly."""
    citation = correction.get("citation") or {}
    doi = (citation.get("doi") or "").strip()
    ref = (citation.get("ref") or "").strip()
    if not doi and not ref:
        return "not-scholarly", ["no scholarly citation carried; "
                                 "ordinary corrections flow applies"]
    reasons = []
    by_doi, by_ref = load_register(root)
    found = None
    if doi:
        found = by_doi.get(doi.lower())
        if found is None and resolver is not None:
            hit = resolver.resolve(doi)
            if hit is not None:
                reasons.append("Crossref seam resolved the DOI but it "
                               "is not in the scholarly register; "
                               "register it on the record first")
        if found is None:
            reasons.append(f"DOI {doi} does not resolve in the "
                           f"scholarly register")
    if ref:
        found = by_ref.get(ref) or found
        if ref not in by_ref:
            reasons.append(f"ref {ref} not in the scholarly register")
    if not (citation.get("quote") or "").strip():
        reasons.append("citation carries no supporting quote")
    if not (citation.get("locator") or "").strip():
        reasons.append("citation carries no stable locator")
    if reasons:
        return "rejected", reasons
    return "accepted", [f"citation resolves in the register: "
                         f"{doi or ref}"]


def cmd_check(root: Path, path: Path):
    try:
        correction = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"cannot read correction: {exc}", file=sys.stderr)
        return 2
    verdict, reasons = gate(root, correction)
    print(json.dumps({"verdict": verdict, "reasons": reasons},
                     indent=2, sort_keys=True))
    return 1 if verdict == "rejected" else 0


def cmd_register(root: Path, path: Path):
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"cannot read source record: {exc}", file=sys.stderr)
        return 2
    if not (rec.get("doi") or rec.get("ref")):
        print("source record needs a doi or a ref", file=sys.stderr)
        return 2
    reg = root / REGISTER_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    with reg.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"registered {rec.get('doi') or rec.get('ref')}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "register"):
        p = sub.add_parser(name)
        p.add_argument("file")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "check":
        return cmd_check(root, Path(args.file))
    return cmd_register(root, Path(args.file))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
