#!/usr/bin/env python3
"""wiki_rank_expr.py — tooling for the Vespa-style rank expressions.

Marathon Round 3, lane TB7, row 2. Pattern: Vespa's single-pass
rank expressions (Vespa, Apache-2.0 — re-implemented from the
idea, no code copied): a ranking is STATED as one small
declarative arithmetic expression over named per-candidate
features, and scoring is one evaluation of that expression per
candidate — no expression may re-run a ranker or re-scan the
corpus.

The canonical implementation of the language (parser, evaluator,
feature set, named expressions) lives in scripts/wiki_search.py,
because the hybrid ranker itself evaluates
RANK_EXPRESSIONS["hybrid-current"] for every candidate — the
shipped ranking and the stated expression are the same object and
cannot drift. This module is the tooling surface over it:

    python3 scripts/wiki_rank_expr.py list
    python3 scripts/wiki_rank_expr.py show hybrid-current
    python3 scripts/wiki_rank_expr.py eval hybrid-current \\
        bm25_norm=1.0 ppr_norm=0.5 temporal=0 rerank=1.2 title_boost=10
    python3 scripts/wiki_rank_expr.py check

`check` parses every named expression and evaluates each over a
zero feature vector and an all-ones feature vector; exit 1 if any
named expression is malformed. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_search():
    spec = importlib.util.spec_from_file_location(
        "wiki_search_for_rank_expr", Path(__file__).with_name("wiki_search.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load_search()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="accepted for CLI uniformity; unused")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the named expressions + features")
    sp = sub.add_parser("show", help="show one named expression")
    sp.add_argument("name")
    sp = sub.add_parser("eval", help="evaluate an expression over features")
    sp.add_argument("name", help="a named expression or a raw expression")
    sp.add_argument("features", nargs="*", help="name=value pairs")
    sub.add_parser("check", help="validate every named expression")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print(json.dumps({
            "kind": "rank-expressions",
            "features": sorted(ws.RANK_FEATURES),
            "expressions": ws.RANK_EXPRESSIONS,
        }, indent=2, sort_keys=True))
        return 0
    if args.cmd == "show":
        if args.name not in ws.RANK_EXPRESSIONS:
            print(f"unknown expression {args.name!r}; "
                  f"known: {sorted(ws.RANK_EXPRESSIONS)}", file=sys.stderr)
            return 2
        print(ws.RANK_EXPRESSIONS[args.name])
        return 0
    if args.cmd == "eval":
        feats = {}
        for pair in args.features:
            if "=" not in pair:
                print(f"bad feature pair {pair!r} (want name=value)",
                      file=sys.stderr)
                return 2
            k, v = pair.split("=", 1)
            try:
                feats[k] = float(v)
            except ValueError:
                print(f"bad feature value {v!r}", file=sys.stderr)
                return 2
        try:
            ast = ws.rank_expression_ast(args.name)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"expression": args.name, "features": feats,
                          "score": ws.eval_rank_expression(ast, feats)}))
        return 0
    # check
    bad = []
    for name in sorted(ws.RANK_EXPRESSIONS):
        try:
            ast = ws.rank_expression_ast(name)
            ws.eval_rank_expression(ast, {})
            ws.eval_rank_expression(
                ast, {f: 1.0 for f in ws.RANK_FEATURES})
        except ValueError as exc:
            bad.append({"name": name, "error": str(exc)})
    print(json.dumps({"kind": "rank-expression-check",
                      "checked": len(ws.RANK_EXPRESSIONS), "bad": bad}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
