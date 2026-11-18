#!/usr/bin/env python3
"""Cross-copy fixity poll — LOCKSS-style polling across the wiki's copies.

Pattern: the LOCKSS polling & repair doctrine (survey find 8,
`docs/research-notes.md`): many
copies keep stuff safe only when the copies are *compared* on a slow
schedule; a copy that disagrees with the consensus is re-made from a
proven one, and a split vote raises an alarm instead of guessing.

This wiki has three copies of the same corpus:

  (a) the local checkout's git HEAD (this repo),
  (b) the canonical remote (`git ls-remote origin`),
  (c) the nightly take-home zip in cloud storage
      (`wikicitadel-takehome-latest.zip`, rebuilt nightly
      by the take-home job).

Until now they were never compared. This tool is the poll. It is
READ-ONLY: it never repairs, uploads, or rewrites anything; repair
is a separate act taken from a proven copy, exactly as LOCKSS
separates the poll from the repair.

What is compared, per artefact class:

  * HEAD equality — local HEAD vs remote HEAD (the same commit id
    must name both; anything else is DIVERGE, both ids printed).
  * Zip fidelity — the zip carries its own `.git`, so it claims a
    HEAD of its own. A deterministic sample of the files tracked at
    that commit — every file under `wiki/rules/`, every
    `evaluation/*.jsonl`, plus a stride sample of the rest — is
    hashed twice: the member bytes inside the zip vs
    `git show <zip-head>:<path>` from the local clone. Equal bytes
    for the same claimed commit = the zip is a faithful copy of
    what it claims to be. A sampled member whose bytes differ, or
    that is missing from the zip, is named as DIVERGE.
  * Zip currency — the zip is a nightly snapshot, so it normally
    lags HEAD. Currency (commits behind, zip HEAD date vs local
    HEAD date) is REPORTED, and counts as AGREE-with-note by
    default: a faithful snapshot a night behind is the designed
    state, and a poll that cried DIVERGE every night would teach
    its reader to ignore it. `--strict` makes any currency lag a
    DIVERGE for callers who want that reading.

Verdicts are per class and overall: AGREE / DIVERGE (the differing
files are named) / UNREACHABLE (the copy and why: ls-remote failed,
Drive listing failed, the zip is unparseable…). Exit 0 only on an
overall AGREE; 1 on DIVERGE or UNREACHABLE; 2 on usage error.

Usage:
  python3 scripts/wiki_fixity.py --zip /tmp/wikicitadel-takehome.zip
  python3 scripts/wiki_fixity.py --drive            # fetch the Drive copy
  python3 scripts/wiki_fixity.py --drive --json     # machine-readable

Stdlib only (the Drive fetch shells out to the connected
the deployment's Drive CLI (env WIKICITADEL_DRIVE_CLI),
the same CLI the nightly job uses).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVE_ZIP_NAME = "wikicitadel-takehome-latest.zip"
# The deployment's Drive CLI (a `drive files list/get` shape);
DRIVE_CLI = os.environ.get("WIKICITADEL_DRIVE_CLI", "gws-cli")

# Sample design: everything in these classes is always hashed; the
# rest of the tree is stride-sampled so the sample stays bounded
# and deterministic (same tree + same target => same sample).
ALWAYS_PREFIXES = ("wiki/rules/",)
ALWAYS_SUFFIX_GLOBS = ("evaluation/*.jsonl",)
DEFAULT_SAMPLE_TARGET = 48


# ---------------------------------------------------------------------------
# Small helpers (kept pure where the tests need them)
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _glob_match(path: str, pattern: str) -> bool:
    """Tiny matcher for the one-star patterns used above."""
    if "*" not in pattern:
        return path == pattern
    pre, post = pattern.split("*", 1)
    return path.startswith(pre) and path.endswith(post)


def choose_sample(tracked, target=DEFAULT_SAMPLE_TARGET):
    """Deterministic sample of `tracked` (sorted repo-relative paths).

    Every path under ALWAYS_PREFIXES or matching ALWAYS_SUFFIX_GLOBS
    is always in; the remainder is stride-sampled (evenly spaced,
    first element included) to roughly `target` additional paths.
    """
    tracked = sorted(tracked)
    always = [p for p in tracked
              if p.startswith(ALWAYS_PREFIXES)
              or any(_glob_match(p, g) for g in ALWAYS_SUFFIX_GLOBS)]
    rest = [p for p in tracked if p not in set(always)]
    if target <= 0 or not rest:
        return always
    stride = max(1, len(rest) // target)
    return always + rest[::stride]


def compare_hashes(zip_hashes, tree_hashes):
    """Compare two {path: sha256} maps over their union of keys.

    Returns (verdict, divergent) where divergent is a sorted list of
    {"path", "reason", "zip", "tree"} — reason is "bytes differ" or
    "missing from zip" / "missing from tree sample". Pure function:
    this is the comparison the fixture tests exercise.
    """
    divergent = []
    for path in sorted(set(zip_hashes) | set(tree_hashes)):
        z, t = zip_hashes.get(path), tree_hashes.get(path)
        if z is None:
            divergent.append({"path": path, "reason": "missing from zip",
                              "zip": None, "tree": t})
        elif t is None:
            divergent.append({"path": path, "reason": "missing from tree",
                              "zip": z, "tree": None})
        elif z != t:
            divergent.append({"path": path, "reason": "bytes differ",
                              "zip": z, "tree": t})
    return ("DIVERGE" if divergent else "AGREE"), divergent


# ---------------------------------------------------------------------------
# Git + zip access
# ---------------------------------------------------------------------------

def _run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=300)


def git_head(root, ref="HEAD"):
    r = _run(["git", "-C", str(root), "rev-parse", ref])
    if r.returncode != 0:
        raise RuntimeError(f"git rev-parse {ref} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def git_commit_date(root, commit):
    r = _run(["git", "-C", str(root), "log", "-1", "--format=%cI", commit])
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def git_ls_remote(root, remote, branch):
    """Return (head_or_None, error_or_None)."""
    r = _run(["git", "-C", str(root), "ls-remote", remote,
              f"refs/heads/{branch}"])
    if r.returncode != 0:
        return None, (r.stderr.strip() or f"ls-remote exited {r.returncode}")
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{branch}":
            return parts[0], None
    return None, f"remote {remote} has no refs/heads/{branch}"


def git_tracked_files(root, commit):
    r = _run(["git", "-C", str(root), "ls-tree", "-r", "--name-only", commit])
    if r.returncode != 0:
        raise RuntimeError(f"git ls-tree {commit} failed: {r.stderr.strip()}")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def git_show_hash(root, commit, rel):
    """sha256 of `git show <commit>:<rel>` streamed, or None if absent."""
    p = subprocess.Popen(["git", "-C", str(root), "show", f"{commit}:{rel}"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    h = hashlib.sha256()
    n = 0
    while True:
        chunk = p.stdout.read(1024 * 1024)
        if not chunk:
            break
        h.update(chunk)
        n += len(chunk)
    rc = p.wait()
    if rc != 0:
        return None
    return h.hexdigest()


def zip_head_commit(zip_path, workdir):
    """The HEAD commit the zip claims, from its own embedded .git.

    Extracts only the .git members into workdir and asks git. Returns
    (commit, date) or raises RuntimeError with the reason.
    """
    zf = zipfile.ZipFile(zip_path)
    prefix = None
    for name in zf.namelist():
        if name.endswith("/.git/HEAD"):
            prefix = name[: -len(".git/HEAD")]
            break
    if prefix is None:
        raise RuntimeError("zip carries no .git/HEAD — not a wiki take-home zip")
    dest = Path(workdir)
    for name in zf.namelist():
        if name.startswith(prefix + ".git/") and not name.endswith("/"):
            target = dest / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    repo = dest
    head = git_head(repo)
    return head, git_commit_date(repo, head), prefix


def zip_member_hash(zip_path, member):
    zf = zipfile.ZipFile(zip_path)
    try:
        info = zf.getinfo(member)
    except KeyError:
        return None
    h = hashlib.sha256()
    with zf.open(info) as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fetch_drive_zip(dest):
    """Download the Drive take-home zip to dest via the connected CLI.

    Returns (file_record, error). Read-only: list + get only.
    """
    q = f"name = '{DRIVE_ZIP_NAME}' and trashed = false"
    r = _run([DRIVE_CLI, "drive", "files", "list", "--params",
              json.dumps({"q": q, "fields":
                          "files(id,name,size,modifiedTime,md5Checksum)"})])
    if r.returncode != 0:
        return None, f"drive list failed: {(r.stderr or r.stdout).strip()[:300]}"
    try:
        files = json.loads(r.stdout).get("files") or []
    except Exception as exc:
        return None, f"drive list unparseable: {exc}"
    if not files:
        return None, f"no live file named {DRIVE_ZIP_NAME} in Drive"
    rec = files[0]
    r = _run([DRIVE_CLI, "drive", "files", "get", "--params",
              json.dumps({"fileId": rec["id"], "alt": "media"}),
              "--output", str(dest)])
    if r.returncode != 0:
        return None, f"drive download failed: {(r.stderr or r.stdout).strip()[:300]}"
    return rec, None


# ---------------------------------------------------------------------------
# The poll
# ---------------------------------------------------------------------------

def poll(root, zip_path=None, remote="origin", branch="master",
         sample_target=DEFAULT_SAMPLE_TARGET, strict=False):
    """Run the three-copy poll. Returns the report dict (JSON-safe)."""
    root = Path(root)
    report = {"tool": "wiki_fixity poll", "root": str(root),
              "classes": {}, "overall": None}

    local_head = git_head(root)
    local_date = git_commit_date(root, local_head)
    report["local"] = {"head": local_head, "head_date": local_date}

    # --- copy (b): remote HEAD-------------------------------------------------
    remote_head, remote_err = git_ls_remote(root, remote, branch)
    if remote_err is not None:
        report["remote"] = {"reachable": False, "error": remote_err}
        report["classes"]["head_equality"] = {
            "verdict": "UNREACHABLE", "copy": f"remote ({remote})",
            "why": remote_err}
    else:
        report["remote"] = {"reachable": True, "head": remote_head}
        verdict = "AGREE" if remote_head == local_head else "DIVERGE"
        report["classes"]["head_equality"] = {
            "verdict": verdict, "local_head": local_head,
            "remote_head": remote_head}

    # --- copy (c): the Drive zip ---------------------------------------------
    if zip_path is None:
        report["classes"]["zip_fidelity"] = {
            "verdict": "UNREACHABLE", "copy": "drive zip",
            "why": "no zip supplied (pass --zip PATH or --drive)"}
        report["classes"]["zip_currency"] = {
            "verdict": "UNREACHABLE", "copy": "drive zip",
            "why": "no zip supplied (pass --zip PATH or --drive)"}
    else:
        zip_path = Path(zip_path)
        try:
            with tempfile.TemporaryDirectory(prefix="fixity-git-") as td:
                z_head, z_date, prefix = zip_head_commit(zip_path, td)
        except Exception as exc:
            report["classes"]["zip_fidelity"] = {
                "verdict": "UNREACHABLE", "copy": "drive zip",
                "why": f"cannot read the zip's embedded HEAD: {exc}"}
            report["classes"]["zip_currency"] = {
                "verdict": "UNREACHABLE", "copy": "drive zip",
                "why": "zip HEAD unreadable"}
        else:
            report["zip"] = {"path": str(zip_path), "head": z_head,
                              "head_date": z_date, "member_prefix": prefix}
            tracked = git_tracked_files(root, z_head)
            sample = choose_sample(tracked, sample_target)
            tree_hashes, zip_hashes = {}, {}
            for rel in sample:
                th = git_show_hash(root, z_head, rel)
                if th is not None:
                    tree_hashes[rel] = th
                zh = zip_member_hash(zip_path, prefix + rel)
                if zh is not None:
                    zip_hashes[rel] = zh
            # compare_hashes reports a tracked file with no zip member
            # as "missing from zip" and a byte mismatch as "bytes differ".
            verdict, divergent = compare_hashes(zip_hashes, tree_hashes)
            report["classes"]["zip_fidelity"] = {
                "verdict": verdict, "against_commit": z_head,
                "sample_size": len(sample), "tracked_files": len(tracked),
                "divergent": divergent}

            # Currency: zip HEAD vs local HEAD.
            if z_head == local_head:
                currency = {"verdict": "AGREE", "commits_behind": 0,
                            "zip_head_date": z_date,
                            "local_head_date": local_date}
            else:
                r = _run(["git", "-C", str(root), "rev-list", "--count",
                          f"{z_head}..{local_head}"])
                behind = int(r.stdout.strip()) if r.returncode == 0 else None
                ancestor = _run(["git", "-C", str(root), "merge-base",
                                 "--is-ancestor", z_head, local_head]
                                ).returncode == 0
                currency = {
                    "verdict": "DIVERGE" if strict else "AGREE",
                    "note": ("zip is an older snapshot (nightly lag)"
                             if ancestor else
                             "zip HEAD is NOT an ancestor of local HEAD"),
                    "commits_behind": behind, "is_ancestor": ancestor,
                    "zip_head_date": z_date, "local_head_date": local_date,
                    "strict": strict}
            report["classes"]["zip_currency"] = currency

    verdicts = [c["verdict"] for c in report["classes"].values()]
    if "UNREACHABLE" in verdicts:
        report["overall"] = "UNREACHABLE"
    elif "DIVERGE" in verdicts:
        report["overall"] = "DIVERGE"
    else:
        report["overall"] = "AGREE"
    return report


def print_report(report):
    print("== Cross-copy fixity poll (LOCKSS-style) ==")
    loc = report.get("local", {})
    print(f"  local HEAD : {loc.get('head')}  ({loc.get('head_date')})")
    az = report.get("remote", {})
    if az.get("reachable"):
        print(f"  remote HEAD: {az.get('head')}")
    else:
        print(f"  remote     : UNREACHABLE — {az.get('error')}")
    zp = report.get("zip")
    if zp:
        print(f"  zip HEAD   : {zp.get('head')}  ({zp.get('head_date')})"
              f"  [{zp.get('path')}]")
    for name, cls in report["classes"].items():
        line = f"  [{cls['verdict']}] {name}"
        if name == "zip_fidelity" and cls.get("sample_size"):
            line += (f" — sample {cls['sample_size']} of"
                     f" {cls['tracked_files']} tracked files"
                     f" at {cls['against_commit'][:12]}")
        if cls.get("note"):
            line += f" — {cls['note']}"
        if name == "zip_currency" and cls.get("commits_behind") is not None:
            line += (f" — {cls['commits_behind']} commit(s) behind;"
                     f" zip HEAD {cls.get('zip_head_date')} vs"
                     f" local HEAD {cls.get('local_head_date')}")
        if cls.get("why"):
            line += f" — {cls['why']}"
        print(line)
        for d in cls.get("divergent", []):
            print(f"      DIVERGE {d['path']} — {d['reason']}")
    print(f"Result: {report['overall']}")


def main(argv):
    ap = argparse.ArgumentParser(
        description="Cross-copy fixity poll: local vs remote vs Drive zip.")
    ap.add_argument("--root", default=str(ROOT),
                    help="wiki repo root (default: this script's repo)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--zip", dest="zip_path", default=None,
                     help="path to an already-downloaded take-home zip")
    src.add_argument("--drive", action="store_true",
                     help="fetch the current Drive take-home zip first")
    ap.add_argument("--remote", default="origin",
                    help="git remote naming the canonical copy")
    ap.add_argument("--branch", default="master")
    ap.add_argument("--sample-target", type=int,
                    default=DEFAULT_SAMPLE_TARGET,
                    help="stride-sample size beyond the always-included"
                         " classes (default 48)")
    ap.add_argument("--strict", action="store_true",
                    help="count zip currency lag as DIVERGE")
    ap.add_argument("--json", action="store_true",
                    help="print the report as JSON")
    args = ap.parse_args(argv[1:])

    zip_path = args.zip_path
    drive_rec = None
    if args.drive:
        tmp = Path(tempfile.gettempdir()) / "wikicitadel-takehome.zip"
        drive_rec, err = fetch_drive_zip(tmp)
        if err is not None:
            report = {"tool": "wiki_fixity poll", "overall": "UNREACHABLE",
                      "classes": {"zip_fidelity": {
                          "verdict": "UNREACHABLE", "copy": "drive zip",
                          "why": err}}}
            print(json.dumps(report, indent=2) if args.json else
                  f"Drive zip UNREACHABLE — {err}\nResult: UNREACHABLE")
            return 1
        zip_path = str(tmp)

    report = poll(args.root, zip_path=zip_path, remote=args.remote,
                  branch=args.branch, sample_target=args.sample_target,
                  strict=args.strict)
    if drive_rec:
        report["drive_file"] = {k: drive_rec.get(k) for k in
                                ("id", "name", "size", "modifiedTime",
                                 "md5Checksum")}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    return 0 if report["overall"] == "AGREE" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
