#!/usr/bin/env python3
"""Retraction-propagation audit register (van der Vet & Nijveen pattern).

Marathon R10 lane BA (ideas board R8 research, Tier A): van der Vet
& Nijveen, Res Integr Peer Rev 2016 (CC BY 4.0) — pattern only.
For a withdrawn/superseded source, this tool lists:
  (a) DIRECT pages: pages directly citing the source (citation
      lockfile citations + frontmatter `sources:`), each requiring
      a text-level check of whether the withdrawn claim is repeated;
  (b) INDIRECT dependents: pages that link to a direct page
      ([[wikilinks]]) but do not themselves cite the source —
      a separate lower-priority slice, promoted only when the
      page text matches a keyword/claim term from the withdrawal
      record (or --keywords).
Report-only: this tool never edits a wiki page. The register
evaluation/retraction-audit.jsonl is append-only; a withdrawal is
recorded with `record`, audits are computed with `report`, and
register integrity is verified with `check`.
Exit 0 ok; 1 = check found invalid lines; 2 = usage error.
Stdlib only, no network, no model call.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "retraction-audit.jsonl"
LOCKFILE = ROOT / "evaluation" / "citation-lockfile.json"


def load_register(path=None):
    p = Path(path) if path else REGISTER
    records, errors = [], []
    if not p.is_file():
        return records, [f"register missing: {p}"]
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        if obj.get("kind") == "header":
            continue
        if obj.get("kind") != "withdrawal":
            errors.append(f"line {i}: kind must be 'withdrawal'")
            continue
        for f in ("source", "reason", "recorded"):
            if not obj.get(f):
                errors.append(f"line {i}: missing field {f!r}")
        records.append(obj)
    return records, errors


def load_lockfile(path=None):
    p = Path(path) if path else LOCKFILE
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("citations", [])


def _frontmatter_sources(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return []
    out, in_sources = [], False
    for line in m.group(1).splitlines():
        if re.match(r"^sources\s*:", line):
            in_sources = True
            rest = line.split(":", 1)[1].strip().strip("[]")
            if rest:
                out += [s.strip().strip("'\"") for s in rest.split(",") if s.strip()]
            continue
        if in_sources:
            mm = re.match(r"^\s*-\s*(.+)$", line)
            if mm:
                out.append(mm.group(1).strip().strip("'\""))
                continue
            in_sources = False
    return out


def build_audit(root, source, keywords):
    root = Path(root)
    citations = load_lockfile(root / "evaluation" / "citation-lockfile.json")
    direct = {}
    for c in citations:
        if c.get("source") == source:
            direct.setdefault(c["page"], {"page": c["page"], "via": "lockfile",
                                          "citation_ids": []})["citation_ids"].append(c.get("id"))
    wiki = root / "wiki"
    page_text = {}
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            text = p.read_text(encoding="utf-8", errors="replace")
            page_text[rel] = text
            if source in _frontmatter_sources(text) and rel not in direct:
                direct[rel] = {"page": rel, "via": "frontmatter", "citation_ids": []}
    direct_stems = {Path(k).stem for k in direct}
    indirect = []
    link_re = re.compile(r"\[\[([^\]|#]+)")
    for rel, text in page_text.items():
        if rel in direct:
            continue
        targets = {Path(t.strip()).stem for t in link_re.findall(text)}
        if targets & direct_stems:
            low = text.lower()
            matched = [k for k in keywords if k and k.lower() in low]
            indirect.append({"page": rel, "links_to_direct": sorted(targets & direct_stems),
                             "promoted": bool(matched), "matched_keywords": matched})
    indirect.sort(key=lambda r: (not r["promoted"], r["page"]))
    return {"source": source, "keywords": list(keywords),
            "direct_count": len(direct),
            "direct": sorted(direct.values(), key=lambda r: r["page"]),
            "indirect_count": len(indirect),
            "indirect_promoted_count": sum(1 for r in indirect if r["promoted"]),
            "indirect": indirect}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Retraction-propagation audit (report-only).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report"); pr.add_argument("--source", required=True)
    pr.add_argument("--keywords", default=""); pr.add_argument("--json", action="store_true")
    pr.add_argument("--register", default=None); pr.add_argument("--root", default=None)
    pc = sub.add_parser("record"); pc.add_argument("--source", required=True)
    pc.add_argument("--reason", required=True); pc.add_argument("--keywords", default="")
    pc.add_argument("--recorded", default=None); pc.add_argument("--register", default=None)
    pk = sub.add_parser("check"); pk.add_argument("--register", default=None)
    args = ap.parse_args(argv)
    cmd = args.command or "check"
    if cmd == "check":
        _recs, errors = load_register(args.register)
        for e in errors:
            print(f"retraction-audit: {e}", file=sys.stderr)
        print(f"retraction-audit: register {'INVALID' if errors else 'valid'} ({len(_recs)} withdrawal(s))")
        return 1 if errors else 0
    if cmd == "record":
        rec = {"kind": "withdrawal", "source": args.source, "reason": args.reason,
               "keywords": [k.strip() for k in args.keywords.split(",") if k.strip()],
               "recorded": args.recorded or date.today().isoformat()}
        p = Path(args.register) if args.register else REGISTER
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"retraction-audit: recorded withdrawal of {args.source}")
        return 0
    records, _ = load_register(args.register)
    kw = [k.strip() for k in args.keywords.split(",") if k.strip()]
    for r in records:
        if r.get("source") == args.source:
            kw = kw or r.get("keywords", [])
    rep = build_audit(Path(args.root) if args.root else ROOT, args.source, kw)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"retraction-audit for {args.source}: {rep['direct_count']} direct page(s) "
              f"requiring text-level check; {rep['indirect_count']} indirect dependent(s), "
              f"{rep['indirect_promoted_count']} promoted on keyword/claim match")
        for d in rep["direct"]:
            print(f"  DIRECT {d['page']} (via {d['via']})")
        for d in rep["indirect"]:
            print(f"  {'PROMOTED' if d['promoted'] else 'indirect'} {d['page']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
