#!/usr/bin/env python3
"""Restore verification — a backup counts only when a restore passes.

Pattern: the Ma.gnolia lesson (survey find 12,
`docs/research-notes.md`): a
single-operator system whose backup *copied its own corruption* and
whose restores were never tested lost everything. The standing
rule this tool enforces: **a backup counts only when a restore
from it has been performed and verified**; a copy that merely
exists is a hope.

Given a take-home zip (normally the Drive copy fetched by
`scripts/wiki_fixity.py --drive`), this tool:

  1. checks the zip's integrity (CRC over every member — a corrupt
     member is named, and the restore stops there: bytes that fail
     CRC are not restored and called good);
  2. extracts it into a FRESH temporary directory (never the live
     tree, never an existing checkout);
  3. verifies the restored copy *as a wiki*, with the wiki's own
     tools run inside the restored root:
       - provenance:  scripts/wiki_provenance.py --verify
       - cite-lock:   scripts/wiki_cite_lock.py check
       - validator:   scripts/wiki_validate.py
       - search smoke: three fixed queries through
         scripts/wiki_search.py, each must return >= 1 hit;
  4. reports every check's verdict individually. The restore
     COUNTS only when all of them pass — a partial pass is a
     failed restore with named causes, not a qualified success.

Exit 0 = the restore counts; 1 = it does not; 2 = usage error.
The temporary restore directory is removed afterwards unless
--keep is given. Read-only with respect to the live wiki and to
Drive: the zip is an input, nothing is written back anywhere.

Usage:
  python3 scripts/wiki_restore_check.py /tmp/wikicitadel-takehome.zip
  python3 scripts/wiki_restore_check.py <zip> --keep   # keep the restore

Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Fixed smoke queries: ordinary questions whose answers have been in
# the corpus , so a healthy restore of any recent
# zip must answer all three. A query passes when the search exits 0
# and reports at least one hit ("Hits: N" with N >= 1).
DEFAULT_QUERIES = ("Agent filings", "Demo project hosting",
                   "Karpathy LLM wiki")

HITS_RE = re.compile(r"Hits:\s*(\d+)")


def run_cmd(argv, cwd):
    """(exit_code, combined_output). The FULL output is returned:
    callers that parse it (the search smoke reads the "Hits: N"
    header at the TOP of the output) must see all of it; display
    truncation happens where a detail string is stored, never
    before a parse. (First real run: a tail-truncated
    capture hid the header and reported a healthy 135-hit query
    as 0 hits — the tool's own bug, found by the drill.)"""
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           timeout=900)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out.strip()
    except Exception as exc:  # missing interpreter, timeout, …
        return None, f"could not run {argv[0]}: {exc}"


def tail(text, limit=600):
    return text[-limit:] if len(text) > limit else text


def find_wiki_root(extract_dir):
    """The restored wiki root: the single directory (or the extract
    dir itself) that carries scripts/wiki_validate.py."""
    candidates = [extract_dir] + sorted(
        p for p in extract_dir.iterdir() if p.is_dir())
    for cand in candidates:
        if (cand / "scripts" / "wiki_validate.py").is_file():
            return cand
    return None


def check_zip_integrity(zip_path):
    """(ok, bad_member_or_None, member_count). CRC over all members."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except Exception as exc:
        return False, f"unreadable zip: {exc}", 0
    bad = zf.testzip()
    return bad is None, bad, len(zf.namelist())


def verify_restored(root, queries=DEFAULT_QUERIES):
    """Run the wiki's own checks inside the restored root.

    Returns a list of check dicts: {name, ok, detail}. This is the
    seam the tests drive with stub tools.
    """
    checks = []
    py = sys.executable or "python3"

    rc, out = run_cmd([py, "scripts/wiki_provenance.py", "--verify"], root)
    checks.append({"name": "provenance --verify", "ok": rc == 0,
                   "detail": tail(out)})

    rc, out = run_cmd([py, "scripts/wiki_cite_lock.py", "check"], root)
    checks.append({"name": "cite-lock check", "ok": rc == 0,
                   "detail": tail(out)})

    rc, out = run_cmd([py, "scripts/wiki_validate.py"], root)
    checks.append({"name": "validator", "ok": rc == 0,
                   "detail": tail(out)})

    for q in queries:
        rc, out = run_cmd([py, "scripts/wiki_search.py", q, "--top", "3"],
                          root)
        m = HITS_RE.search(out)
        hits = int(m.group(1)) if m else 0
        checks.append({"name": f"search smoke: {q!r}",
                       "ok": rc == 0 and hits >= 1,
                       "detail": f"exit {rc}, hits {hits}"})
    return checks


def restore_and_check(zip_path, keep=False, queries=DEFAULT_QUERIES):
    """Full restore verification. Returns the report dict."""
    zip_path = Path(zip_path)
    report = {"tool": "wiki_restore_check", "zip": str(zip_path),
              "checks": [], "counts": False, "restored_root": None}

    ok, bad, count = check_zip_integrity(zip_path)
    report["checks"].append({
        "name": "zip integrity (CRC)", "ok": ok,
        "detail": (f"{count} members, all CRC-clean" if ok
                   else f"corrupt member: {bad}")})
    if not ok:
        return report

    tmp = Path(tempfile.mkdtemp(prefix="restore-check-"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        root = find_wiki_root(tmp)
        if root is None:
            report["checks"].append({
                "name": "restore layout", "ok": False,
                "detail": "no directory carrying scripts/wiki_validate.py"
                          " in the extracted zip"})
            return report
        report["restored_root"] = str(root)
        report["checks"].extend(verify_restored(root, queries))
        report["counts"] = all(c["ok"] for c in report["checks"])
        return report
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
            if report["restored_root"] is not None:
                report["restored_root"] += " (removed after the check)"
        else:
            report["kept"] = True


def print_report(report):
    print(f"== Restore verification ==  zip: {report['zip']}")
    if report.get("restored_root"):
        print(f"  restored to: {report['restored_root']}")
    for c in report["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        detail = c["detail"].replace("\n", " | ")
        if len(detail) > 300:
            detail = "…" + detail[-300:]
        print(f"  [{mark}] {c['name']} — {detail}")
    print("Result:", "RESTORE COUNTS — every check passed"
          if report["counts"] else
          "RESTORE DOES NOT COUNT — see the failed check(s) above")


def main(argv):
    ap = argparse.ArgumentParser(
        description="Restore a take-home zip into a fresh directory and"
                    " verify the restored copy as a wiki.")
    ap.add_argument("zip_path", help="the take-home zip to restore")
    ap.add_argument("--keep", action="store_true",
                    help="keep the restored directory (path is printed)")
    ap.add_argument("--query", action="append", dest="queries",
                    help="override a smoke query (repeatable)")
    args = ap.parse_args(argv[1:])
    if not Path(args.zip_path).is_file():
        print(f"no such zip: {args.zip_path}")
        return 2
    queries = tuple(args.queries) if args.queries else DEFAULT_QUERIES
    report = restore_and_check(args.zip_path, keep=args.keep,
                               queries=queries)
    print_report(report)
    return 0 if report["counts"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
