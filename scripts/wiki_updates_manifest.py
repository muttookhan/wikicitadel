#!/usr/bin/env python3
"""wiki_updates_manifest.py — generated updates manifest.

Marathon R10 lane BB (ideas board R8 deep-dive, Tier A; Crossref
Crossmark pattern — pattern only, NO DOI registration). Generates
evaluation/export-updates-manifest.json from the corrections
ledger (wiki/rules/corrections-ledger.md, parsed for its dated
entries) + the treatment register
(evaluation/treatment-register.jsonl): which exported pages were
later corrected/superseded, by which record, on what date. The
manifest is a DERIVED artefact: regeneration is byte-stable and
`check` verifies it matches the registers. A register a tree
does not carry is reported absent in the manifest, never
treated as empty-and-clean.

Usage: build [--out FILE] | check [--out FILE]
Exit 0 ok; 1 check mismatch; 2 usage error. Stdlib only.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evaluation" / "export-updates-manifest.json"
TREATMENT = ROOT / "evaluation" / "treatment-register.jsonl"
LEDGER = ROOT / "wiki" / "rules" / "corrections-ledger.md"


def treatment_updates(path=None):
    p = Path(path) if path else TREATMENT
    if not p.is_file():
        return None
    updates = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") != "treatment":
            continue
        grade = obj.get("grade")
        status = ("superseded" if grade == "negative"
                  else "corrected" if grade == "questioned"
                  else None)
        if status is None:
            continue
        treated_by = obj.get("treated_by") or {}
        if not treated_by and obj.get("by"):
            treated_by = {"source": obj.get("by"),
                          "detail": obj.get("basis")}
        subject = obj.get("subject") or {}
        if not subject.get("page"):
            continue
        updates.append({
            "page": subject["page"],
            "claim": subject.get("claim"),
            "status": status, "date": obj.get("date"),
            "by_record": treated_by.get("source"),
            "by_detail": treated_by.get("detail"),
            "treatment_id": obj.get("id")})
    return updates


def ledger_entries(path=None):
    p = Path(path) if path else LEDGER
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    return [{"date": m.group(1), "title": m.group(2).strip()}
            for m in re.finditer(
                r"^### (\d{4}-\d{2}-\d{2}) — (.+)$", text, re.M)]


def build_manifest(root=None):
    root = Path(root) if root else ROOT
    t = treatment_updates(root / "evaluation"
                          / "treatment-register.jsonl")
    led = ledger_entries(root / "wiki" / "rules"
                         / "corrections-ledger.md")
    updates = sorted(t or [],
                     key=lambda u: (u["page"], u["date"] or "",
                                    u["treatment_id"] or ""))
    return {
        "tool": "wiki_updates_manifest",
        "pattern": "Crossref Crossmark (pattern only; no DOI "
                   "registration)",
        "sources": {
            "treatment_register": (
                "present" if t is not None else "absent"),
            "corrections_ledger": (
                "present" if led is not None else "absent")},
        "ledger_entries": led or [],
        "updates": updates,
        "updated_pages": sorted({u["page"] for u in updates})}


def render(manifest):
    return json.dumps(manifest, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "check"):
        p = sub.add_parser(name)
        p.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = render(build_manifest())
    if a.cmd == "build":
        Path(a.out).write_text(text, encoding="utf-8")
        m = json.loads(text)
        print(f"wrote {a.out}: {len(m['updates'])} update(s) over "
              f"{len(m['updated_pages'])} page(s)")
        return 0
    cur = Path(a.out)
    if not cur.is_file() or cur.read_text(encoding="utf-8") != text:
        print("manifest does not match the registers")
        return 1
    print("manifest matches the registers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
