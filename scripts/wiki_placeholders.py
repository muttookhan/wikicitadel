#!/usr/bin/env python3
"""Placeholders (dangling-link) report — Foam pattern.

Marathon R9 lane BB (ideas board R7 research, Tier A): Foam
(MIT) placeholders. Beside the orphan lint (pages nobody links
to — scripts/wiki_link_health.py) this report lists the other
side: wikilink TARGETS that were never created as pages —
links pointing at pages that do not exist. Each placeholder
is reported with every page that links to it, so creating the
page (or fixing the link) has its demand on the record.

The computation REUSES wiki_link_health.compute() by import —
one resolution semantics for the whole corpus, never a second
invention. REPORT-ONLY: this tool writes nothing and creates
no stub pages; exit 0 even when placeholders exist (they are
findings), 1 only with --strict, 2 on usage error.

Usage:
  python3 scripts/wiki_placeholders.py [--root DIR] [--json]
      [--strict]
Stdlib only, no network.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def placeholders(root=None):
    """{target: sorted [linking pages]} + summary, from the
    link-health computation's broken targets."""
    health = _load("wiki_link_health", HERE / "wiki_link_health.py")
    records, summary = health.compute(Path(root) if root else ROOT)
    by_target = {}
    for rec in records:
        for target in rec["broken_targets"]:
            by_target.setdefault(target, []).append(rec["page"])
    by_target = {t: sorted(ps) for t, ps in sorted(by_target.items())}
    return {"placeholders": by_target,
            "placeholder_count": len(by_target),
            "dangling_links_total": sum(len(v) for v in by_target.values()),
            "pages_scanned": summary["pages"]}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Report dangling wikilink targets (placeholders).")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    try:
        rep = placeholders(args.root)
    except Exception as exc:  # no wiki layer etc.
        print(f"wiki_placeholders: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        for target, pages in rep["placeholders"].items():
            print(f"  [[{target}]] — linked from {len(pages)} page(s): "
                  + ", ".join(pages))
        print(f"placeholders: {rep['placeholder_count']} never-created "
              f"target(s), {rep['dangling_links_total']} dangling "
              f"link(s) over {rep['pages_scanned']} page(s) "
              f"(report-only)")
    if args.strict and rep["placeholder_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
