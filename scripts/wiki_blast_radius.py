#!/usr/bin/env python3
"""Source-withdrawal blast-radius DRY RUN (Marathon R3 lane
TB1, row 3).

Pattern adapted with credit from LightRAG (HKUDS, MIT —
document deletion regenerating the affected knowledge graph):
before a source is withdrawn, report exactly what its
withdrawal would do, and change NOTHING.

The claim->source incidence map is the wiki's own record:
every compiled page's frontmatter ``sources:`` list is the set
of sources supporting that page's claims (a page carrying a
frontmatter ``claim:`` is a claim unit; every other compiled
page is a page unit). For a candidate withdrawal of source S:

- **sever** — units whose support set is exactly {S}: losing
  S empties their support; they would sever from retrieval
  (kept in the preservation layer, never deleted — the report
  only NAMES them);
- **re-verify** — units whose support set contains S plus at
  least one surviving source: they would stay, but must be
  re-verified verbatim against the survivors;
- **cascade** — pages that cite (wikilink / claim-cite) a
  would-sever unit: flagged for re-verification too, since
  their ground is about to move.

This tool is READ-ONLY in every mode: it writes no file,
appends no register line, and severs nothing. The owner
approves a blast radius first; the severing act, if any, is a
separate operation by its own machinery.

Usage:
  python3 scripts/wiki_blast_radius.py --source raw/sources/x.md
          [--root DIR] [--json]

Exit 0 = report produced (even when the radius is large —
size is a finding, not a failure); 2 = usage error (source
argument names nothing any page cites and no such file).
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_source_hash():
    path = Path(__file__).resolve().parent / "wiki_source_hash.py"
    spec = importlib.util.spec_from_file_location("wiki_source_hash", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_sh = _load_source_hash()


def _norm(path: str) -> str:
    p = str(path).strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def blast_radius(root: Path, source: str) -> dict:
    """The dry-run report for withdrawing *source* under *root*."""
    root = Path(root)
    target = _norm(source)
    pages = _sh.collect_pages(root)
    sever, reverify = [], []
    for rel in sorted(pages):
        supports = {_norm(s) for s in pages[rel]["sources"]}
        if target not in supports:
            continue
        entry = {"page": rel, "supports": sorted(supports),
                 "remaining": sorted(supports - {target})}
        if supports == {target}:
            sever.append(entry)
        else:
            reverify.append(entry)
    severed_pages = {e["page"] for e in sever}
    cascade = []
    for rel in sorted(pages):
        hit = sorted(set(pages[rel]["edges"]) & severed_pages)
        if hit and rel not in severed_pages:
            cascade.append({"page": rel, "cites_severed": hit})
    return {
        "kind": "blast-radius-dry-run",
        "dry_run": True,
        "changed_nothing": True,
        "source": target,
        "source_exists_on_disk": (root / target).is_file(),
        "sever": sever,
        "reverify": reverify,
        "cascade_reverify": cascade,
        "summary": {
            "sever": len(sever),
            "reverify": len(reverify),
            "cascade_reverify": len(cascade),
            "unaffected_pages": len(pages) - len(sever) - len(reverify)
                                  - len(cascade),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--source", required=True,
                    help="repo-relative source path to hypothetically withdraw")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    report = blast_radius(root, args.source)
    if not report["source_exists_on_disk"] and report["summary"]["sever"] == 0 \
            and report["summary"]["reverify"] == 0:
        print(f"no such source and no page cites it: {args.source}",
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"DRY RUN — withdrawing {report['source']} would: "
              f"sever {s['sever']}, re-verify {s['reverify']}, "
              f"cascade re-verify {s['cascade_reverify']} "
              f"(nothing was changed)")
        for e in report["sever"]:
            print(f"  SEVER: {e['page']} (support empties)")
        for e in report["reverify"]:
            print(f"  RE-VERIFY: {e['page']} "
                  f"(survivors: {', '.join(e['remaining'])})")
        for e in report["cascade_reverify"]:
            print(f"  CASCADE: {e['page']} cites severed "
                  f"{', '.join(e['cites_severed'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
