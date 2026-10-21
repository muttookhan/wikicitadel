#!/usr/bin/env python3
"""W3C-style image-annotation JSON checker (Annotorious prototype).

Marathon R10 lane BA (ideas board R8 research, Tier A):
Annotorious (BSD-3-Clause) — pattern only, nothing vendored.
Annotations for the prototype live as JSON files ALONGSIDE
(never inside) the images they annotate. This checker validates
that shape: a JSON array (or a single object) of W3C Web
Annotation objects, each with @context containing the W3C anno
context, type "Annotation", a non-empty id, a target with a
source (the image reference), and — when a selector is present —
a FragmentSelector with an xywh value.
Commands: check FILE [FILE ...] [--json]
Exit 0 = all valid; 1 = findings; 2 = usage/IO error.
Stdlib only, no network.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ANNO_CONTEXT = "http://www.w3.org/ns/anno.jsonld"
XYWH = re.compile(r"^xywh=(percent:)?\d+(\.\d+)?,\d+(\.\d+)?,\d+(\.\d+)?,\d+(\.\d+)?$")


def check_annotation(obj, where):
    errs = []
    if not isinstance(obj, dict):
        return [f"{where}: not a JSON object"]
    ctx = obj.get("@context")
    ctxs = ctx if isinstance(ctx, list) else [ctx]
    if ANNO_CONTEXT not in ctxs:
        errs.append(f"{where}: @context must include {ANNO_CONTEXT}")
    if obj.get("type") != "Annotation":
        errs.append(f"{where}: type must be 'Annotation'")
    if not obj.get("id"):
        errs.append(f"{where}: id is required and must be non-empty")
    target = obj.get("target")
    if not isinstance(target, dict) or not target.get("source"):
        errs.append(f"{where}: target.source (the image reference) is required")
    else:
        sel = target.get("selector")
        if sel is not None:
            sels = sel if isinstance(sel, list) else [sel]
            for s in sels:
                if isinstance(s, dict) and s.get("type") == "FragmentSelector":
                    if not XYWH.match(str(s.get("value", ""))):
                        errs.append(f"{where}: FragmentSelector value must be xywh=...")
    body = obj.get("body")
    if body is not None:
        bodies = body if isinstance(body, list) else [body]
        for b in bodies:
            if not isinstance(b, dict) or "value" not in b:
                errs.append(f"{where}: each body must be an object with a value")
    return errs


def check_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path}: cannot read/parse JSON ({e})"], 0
    items = data if isinstance(data, list) else [data]
    errs = []
    for i, obj in enumerate(items):
        errs += check_annotation(obj, f"{path}[{i}]")
    return errs, len(items)


def main(argv=None):
    ap = argparse.ArgumentParser(description="W3C image-annotation JSON checker.")
    sub = ap.add_subparsers(dest="command")
    pc = sub.add_parser("check"); pc.add_argument("files", nargs="+")
    pc.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if (args.command or "check") != "check" or not getattr(args, "files", None):
        ap.print_usage(sys.stderr)
        return 2
    all_errs, total = [], 0
    for f in args.files:
        errs, n = check_file(f)
        all_errs += errs
        total += n
    rep = {"files": args.files, "annotations": total, "errors": all_errs,
           "valid": not all_errs}
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    elif all_errs:
        for e in all_errs:
            print(f"annotation-check: {e}", file=sys.stderr)
        print(f"annotation-check: INVALID ({total} annotation(s), {len(all_errs)} error(s))")
    else:
        print(f"annotation-check: valid ({total} annotation(s) in {len(args.files)} file(s))")
    return 1 if all_errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
