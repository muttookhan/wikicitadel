#!/usr/bin/env python3
"""wiki_citeindex_gate.py — CiteIndex evidence gate (report-only).

Marathon R10 lane BB (ideas board R8 deep-dive, Tier A; CiteIndex
pattern, MIT per catalogue — judged at opened (search-rendered)
level, verification level stated on the board line). Lists
source-record metadata changes — changes to IDENTIFYING fields
of the source catalog (evaluation/source-catalog.json) and the
source manifest (evaluation/source-manifest.jsonl) across git
history — that lack a quote+locator evidence entry. REPORT-ONLY:
never blocks (exit 0 unless usage error), never edits anything.

The evidence-entry shape, AS DATA (EVIDENCE_ENTRY_SHAPE):
  {"source": "<catalog/manifest path key>", "field": "<field>",
   "quote": "<verbatim quote from the record supporting the
   change>", "locator": "<file>#L<a>-L<b> or commit sha>",
   "date": "YYYY-MM-DD"}
Entries live in evaluation/citeindex-evidence.jsonl (absent =
no entries, reported honestly, never treated as clean-by-default
beyond the listing itself).

Usage: report [--json] [--root DIR] [--evidence FILE]
Exit 0 report produced; 2 usage error. Stdlib only.
"""
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_FIELDS = ("name", "path", "licence", "file_count",
                  "total_bytes")
MANIFEST_FIELDS = ("path", "sha256", "size")
EVIDENCE_ENTRY_SHAPE = {
    "source": "str — the catalog collection name or manifest path",
    "field": "str — the identifying field that changed",
    "quote": "str — verbatim quote supporting the change",
    "locator": "str — file#L<a>-L<b> or commit sha",
    "date": "str — YYYY-MM-DD"}


def catalog_changes(old, new):
    """Identifying-field changes between two catalog snapshots."""
    changes = []
    oc = {c.get("name"): c for c in (old or {}).get("collections", [])}
    nc = {c.get("name"): c for c in (new or {}).get("collections", [])}
    for name in sorted(set(oc) | set(nc)):
        if name not in oc:
            changes.append({"source": name, "field": "__added__",
                            "old": None, "new": "present"})
            continue
        if name not in nc:
            changes.append({"source": name, "field": "__removed__",
                            "old": "present", "new": None})
            continue
        for f in CATALOG_FIELDS:
            if oc[name].get(f) != nc[name].get(f):
                changes.append({"source": name, "field": f,
                                "old": oc[name].get(f),
                                "new": nc[name].get(f)})
    return changes


def manifest_changes(old_rows, new_rows):
    changes = []
    om = {r.get("path"): r for r in old_rows or []}
    nm = {r.get("path"): r for r in new_rows or []}
    for path in sorted(set(om) | set(nm)):
        if path not in om:
            changes.append({"source": path, "field": "__added__",
                            "old": None, "new": "present"})
            continue
        if path not in nm:
            changes.append({"source": path, "field": "__removed__",
                            "old": "present", "new": None})
            continue
        for f in MANIFEST_FIELDS:
            if om[path].get(f) != nm[path].get(f):
                changes.append({"source": path, "field": f,
                                "old": om[path].get(f),
                                "new": nm[path].get(f)})
    return changes


def load_evidence(path):
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def lacks_evidence(change, evidence):
    return not any(e.get("source") == change["source"]
                   and e.get("field") == change["field"]
                   and e.get("quote") and e.get("locator")
                   for e in evidence)


def git_history_changes(root):
    """All identifying-field changes across git history of the
    catalog + manifest. Returns (changes, commits_seen). Each
    change is stamped with the commit that introduced it."""
    def show(rev, rel):
        r = subprocess.run(["git", "-C", str(root), "show",
                            f"{rev}:{rel}"], capture_output=True,
                           text=True)
        return r.stdout if r.returncode == 0 else None
    def log(rel):
        r = subprocess.run(["git", "-C", str(root), "log",
                            "--format=%H", "--", rel],
                           capture_output=True, text=True)
        return [l for l in r.stdout.splitlines() if l][::-1]
    changes, commits = [], 0
    for rel, kind in (("evaluation/source-catalog.json", "cat"),
                      ("evaluation/source-manifest.jsonl", "man")):
        revs = log(rel)
        commits += len(revs)
        prev = None
        for rev in revs:
            raw = show(rev, rel)
            if raw is None:
                continue
            if kind == "cat":
                cur = json.loads(raw)
                if prev is not None:
                    for c in catalog_changes(prev, cur):
                        changes.append({**c, "commit": rev})
                prev = cur
            else:
                cur = [json.loads(l) for l in raw.splitlines()
                       if l.strip()]
                if prev is not None:
                    for c in manifest_changes(prev, cur):
                        changes.append({**c, "commit": rev})
                prev = cur
    return changes, commits


def build_report(root, evidence):
    changes, commits = git_history_changes(root)
    lacking = [c for c in changes if lacks_evidence(c, evidence)]
    return {"tool": "wiki_citeindex_gate", "report_only": True,
            "evidence_entry_shape": EVIDENCE_ENTRY_SHAPE,
            "commits_seen": commits,
            "changes_seen": len(changes),
            "changes_lacking_evidence": lacking,
            "lacking_count": len(lacking)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--json", action="store_true")
    r.add_argument("--root", default=str(ROOT))
    r.add_argument("--evidence", default=None)
    a = ap.parse_args(argv)
    root = Path(a.root)
    ev_path = Path(a.evidence) if a.evidence else (
        root / "evaluation" / "citeindex-evidence.jsonl")
    rep = build_report(root, load_evidence(ev_path))
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"citeindex gate (report-only): {rep['changes_seen']}"
              f" identifying-field change(s) over "
              f"{rep['commits_seen']} commit(s); "
              f"{rep['lacking_count']} lack a quote+locator "
              f"evidence entry")
        for c in rep["changes_lacking_evidence"]:
            print(f"  - {c['source']} :: {c['field']} "
                  f"({c.get('commit', '')[:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
