#!/usr/bin/env python3
"""Integration-path merge hygiene (mcp-llm-wiki pattern) —
ETag/pre-hash check + append-coalescing for the coordinator
integration path.

Marathon R12 lane BB (ideas board line 187, deep-dive batch 7,
Tier A): the mcp-llm-wiki integration pattern, restated in our
own words. This is TOOLING FOR THE INTEGRATION WORKFLOW ONLY:
when parallel lanes hand work to a coordinator, the coordinator
integrates files the lanes built in scratch. Two failure modes
bite there, and this tool addresses both WITHOUT changing any
wiki content semantics — it edits no page, decides nothing
about content, and is not a gate over publication:

  (a) Pre-hash (ETag-style) verification: a lane records the
      sha256 of every file it audited. Before integrating, the
      coordinator re-hashes each file; a file whose current hash
      differs from the recorded one (or is missing) is reported
      MISMATCH/MISSING and is NOT silently integrated on the
      strength of the lane's audit. `etag` prints a file's tag
      ("sha256:<hex>"), `manifest` builds the path -> tag map,
      `verify` checks a tree against such a map.
  (b) Append-coalescing: append-only files (an AGENTS.md
      section, log entries) are appended to independently by
      parallel lanes, each append a pure suffix of the shared
      base. `coalesce` merges those suffixes without loss:
      every candidate must be a pure append of the base (else
      it is reported NOT-AN-APPEND and excluded, never forced),
      appended text is split into blocks at heading lines
      (markdown `#`/`##` headings and `## [` log headings),
      exact duplicate blocks collapse, and block order is
      candidate order, then block order within a candidate.
      The result states per candidate what was taken.

This stands BESIDE the existing git merge driver
(scripts/git_merge_append.py, private tree): that driver runs
inside git merges of log/ledger hotspots; this helper runs
BEFORE integration, on plain files, with an auditable report.
Commands: etag / verify / coalesce. Exit 0 ok (verify: all
match); 1 mismatch or not-an-append present; 2 usage error.
Stdlib only, no network.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK_START = re.compile(r"^(#{1,3} |## \[)", re.M)


def file_etag(path):
    """The ETag-style tag for a file: "sha256:<hex of its bytes>"."""
    data = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_manifest(root, relpaths):
    """{relpath: etag} for each named file under root (missing
    files are recorded as null, honestly, not skipped)."""
    root = Path(root)
    out = {}
    for rel in relpaths:
        p = root / rel
        out[rel] = file_etag(p) if p.is_file() else None
    return out


def verify_manifest(root, manifest):
    """Check a tree against a {relpath: etag} manifest.
    Returns [{path, expected, actual, status}] with status in
    match / mismatch / missing / unrecorded (expected null)."""
    root = Path(root)
    rows = []
    for rel in sorted(manifest):
        expected = manifest[rel]
        p = root / rel
        if expected is None:
            rows.append({"path": rel, "expected": None,
                         "actual": file_etag(p) if p.is_file() else None,
                         "status": "unrecorded"})
        elif not p.is_file():
            rows.append({"path": rel, "expected": expected,
                         "actual": None, "status": "missing"})
        else:
            actual = file_etag(p)
            rows.append({"path": rel, "expected": expected,
                         "actual": actual,
                         "status": "match" if actual == expected
                         else "mismatch"})
    return rows


def append_suffix(base, candidate):
    """The suffix candidate adds to base, or None if candidate
    is not a pure append of base."""
    if not candidate.startswith(base):
        return None
    return candidate[len(base):]


def _split_append_blocks(suffix):
    """Split appended text into blocks at heading lines; text
    before the first heading is its own block. Empty blocks
    (pure whitespace) are dropped."""
    starts = [m.start() for m in BLOCK_START.finditer(suffix)]
    if not starts:
        return [suffix] if suffix.strip() else []
    blocks = []
    if suffix[:starts[0]].strip():
        blocks.append(suffix[:starts[0]])
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(suffix)
        blocks.append(suffix[s:e])
    return [b for b in blocks if b.strip()]


def coalesce_appends(base, candidates):
    """Merge parallel pure appends of `base` without loss.

    candidates: [text, ...]. Returns (merged, report) where
    report is one entry per candidate: {index, status:
    appended / not-an-append / empty, blocks_taken,
    blocks_duplicated}. A not-an-append candidate contributes
    NOTHING and is reported — its content is never forced in.
    """
    seen = set()
    taken = []
    report = []
    for i, cand in enumerate(candidates):
        suffix = append_suffix(base, cand)
        if suffix is None:
            report.append({"index": i, "status": "not-an-append",
                           "blocks_taken": 0, "blocks_duplicated": 0})
            continue
        blocks = _split_append_blocks(suffix)
        if not blocks:
            report.append({"index": i, "status": "empty",
                           "blocks_taken": 0, "blocks_duplicated": 0})
            continue
        n_taken = n_dup = 0
        for b in blocks:
            if b in seen:
                n_dup += 1
            else:
                seen.add(b)
                taken.append(b)
                n_taken += 1
        report.append({"index": i, "status": "appended",
                       "blocks_taken": n_taken,
                       "blocks_duplicated": n_dup})
    return base + "".join(taken), report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Integration-path merge hygiene (pre-hash + "
                    "append-coalescing).")
    sub = ap.add_subparsers(dest="command")
    pe = sub.add_parser("etag"); pe.add_argument("file")
    pv = sub.add_parser("verify"); pv.add_argument("manifest")
    pv.add_argument("--root", default=str(ROOT))
    pc = sub.add_parser("coalesce"); pc.add_argument("base")
    pc.add_argument("candidates", nargs="+")
    pc.add_argument("--out", default=None)
    pc.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "etag":
        print(file_etag(args.file))
        return 0
    if args.command == "verify":
        try:
            manifest = json.loads(Path(args.manifest)
                                  .read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"integration-hygiene: cannot read manifest: {e}",
                  file=sys.stderr)
            return 2
        rows = verify_manifest(args.root, manifest)
        bad = 0
        for r in rows:
            print(f"{r['status']}: {r['path']}")
            if r["status"] in ("mismatch", "missing"):
                bad += 1
        print(f"integration-hygiene: {len(rows)} file(s) checked, "
              f"{bad} mismatch/missing")
        return 1 if bad else 0
    if args.command == "coalesce":
        try:
            base = Path(args.base).read_text(encoding="utf-8")
            cands = [Path(c).read_text(encoding="utf-8")
                     for c in args.candidates]
        except OSError as e:
            print(f"integration-hygiene: cannot read input: {e}",
                  file=sys.stderr)
            return 2
        merged, report = coalesce_appends(base, cands)
        if args.out:
            Path(args.out).write_text(merged, encoding="utf-8")
        else:
            sys.stdout.write(merged)
        if args.json:
            print(json.dumps(report, indent=2), file=sys.stderr)
        else:
            for r in report:
                print(f"candidate {r['index']}: {r['status']} "
                      f"(taken {r['blocks_taken']}, duplicated "
                      f"{r['blocks_duplicated']})", file=sys.stderr)
        return 1 if any(r["status"] == "not-an-append"
                        for r in report) else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
