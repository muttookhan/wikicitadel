#!/usr/bin/env python3
"""Review diff helper — Difftastic as the adopted external driver.

Marathon R8 lane BB (ideas board R6 research, Tier A): Difftastic
(MIT) is adopted EXTERNALLY for reviewing lockfile / manifest /
config changes — structural diffs read better than line diffs for
JSON lockfiles and manifests. Nothing is embedded or vendored:
this helper shells to ``difft`` when it is on PATH and degrades
cleanly when it is not.

Portability pattern (the ssh-keygen/ocrmypdf precedent in this
codebase): absence must never fail a run. When ``difft`` is
absent the helper says so in one stated line and falls back to a
stdlib unified diff, exit still 0. No existing gate depends on
this helper; it is a review aid only.

Usage:
  python3 scripts/wiki_review_diff.py FILE_A FILE_B [--json]
Exit: 0 = a diff (either driver) was produced; 2 = usage error
(a file is unreadable). Stdlib only; no network.
"""
import argparse
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ABSENT_MESSAGE = ("difftastic (difft) not on PATH - falling back "
                  "to stdlib unified diff; install difftastic for "
                  "structural review diffs (absence never fails "
                  "this helper)")


def difft_path(which=None):
    """Path to difft, or None. Injectable for tests."""
    return (which or shutil.which)("difft")


def review_diff(path_a, path_b, which=None):
    """Diff two files. Returns a report dict; never raises for a
    missing difft. ``driver`` is 'difftastic' or 'unified-diff'."""
    a, b = Path(path_a), Path(path_b)
    text_a = a.read_text(encoding="utf-8", errors="replace")
    text_b = b.read_text(encoding="utf-8", errors="replace")
    exe = difft_path(which)
    if exe is None:
        diff = "".join(difflib.unified_diff(
            text_a.splitlines(keepends=True),
            text_b.splitlines(keepends=True),
            fromfile=str(a), tofile=str(b)))
        return {"driver": "unified-diff", "difft_available": False,
                "message": ABSENT_MESSAGE,
                "changed": text_a != text_b, "diff": diff}
    proc = subprocess.run(
        [exe, "--display", "inline", str(a), str(b)],
        capture_output=True, text=True)
    # difft exits 0 (no change) or 1 (changes); both are success.
    if proc.returncode not in (0, 1):
        diff = "".join(difflib.unified_diff(
            text_a.splitlines(keepends=True),
            text_b.splitlines(keepends=True),
            fromfile=str(a), tofile=str(b)))
        return {"driver": "unified-diff", "difft_available": True,
                "message": "difft exited %d - fell back to unified "
                           "diff" % proc.returncode,
                "changed": text_a != text_b, "diff": diff}
    return {"driver": "difftastic", "difft_available": True,
            "message": "structural diff by difftastic (difft)",
            "changed": proc.returncode == 1, "diff": proc.stdout}


def main(argv):
    ap = argparse.ArgumentParser(
        description="Review diff (difftastic when present).")
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])
    for f in (args.file_a, args.file_b):
        if not Path(f).is_file():
            print(f"review-diff: file missing: {f}", file=sys.stderr)
            return 2
    report = review_diff(args.file_a, args.file_b)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"driver: {report['driver']} - {report['message']}")
        print(report["diff"], end="")
        print(f"changed: {report['changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
