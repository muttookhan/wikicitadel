#!/usr/bin/env python3
"""Kopia adoption pilot — checkpoint-witness / off-repo tier.

Marathon R9 lane BB (ideas board R7 research, Tier A): Kopia
(Apache-2.0) snapshot tool, PILOT ONLY. The pilot snapshots
a COPY of a wiki tree into a throwaway filesystem repository,
restores it to a separate directory, and verifies restored
SHA-256 hashes against the source copy, recording the
evidence as JSON. The pilot copy is a SIDE-COPY only: it is
never the backup of record (what counts as the backup of
record remains the owner's decision), and the existing
Drive zip flow is untouched.

Safety rails, enforced in code:
  * the source must be an explicit --source directory;
  * the source may NOT be this script's own repository root
    (a pilot never snapshots a real tree — copy it first);
  * kopia is an EXTERNAL binary given by --kopia or PATH; it
    is never vendored into the tree;
  * the repository + cache live under the explicit --work
    directory, outside any wiki tree.

Usage:
  python3 scripts/wiki_kopia_pilot.py run --source COPY_DIR
      --work WORK_DIR [--kopia PATH] [--evidence FILE]
Exit 0 = restore verified hash-for-hash; 1 = pilot failed
(the evidence file records where); 2 = usage/safety refusal.
Stdlib only; the only subprocesses are kopia itself.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILOT_PASSWORD = "kopia-pilot-throwaway"  # pilot repo only


def sha256_tree(base):
    base = Path(base)
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out[p.relative_to(base).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def _run(cmd, env, evidence, label):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=env, timeout=600)
    except OSError as exc:
        class _P:
            returncode = 127
            stdout = ""
            stderr = str(exc)
        proc = _P()
    evidence["steps"].append(
        {"step": label, "argv": [str(c) for c in cmd],
         "exit": proc.returncode,
         "stdout_tail": proc.stdout.strip()[-500:],
         "stderr_tail": proc.stderr.strip()[-500:]})
    return proc


def pilot(source, work, kopia=None, evidence_path=None):
    source, work = Path(source), Path(work)
    evidence = {"tool": "wiki_kopia_pilot", "steps": [],
                "verified": False}
    if not source.is_dir():
        evidence["error"] = f"source not a directory: {source}"
        return evidence, 2
    if source.resolve() == ROOT.resolve():
        evidence["error"] = ("refused: source is this script's own "
                             "repository root — a pilot snapshots "
                             "a COPY, never a real tree")
        return evidence, 2
    binary = kopia or shutil.which("kopia")
    if not binary:
        evidence["error"] = "kopia binary not found (not on PATH, "\
                            "no --kopia given)"
        return evidence, 1
    evidence["kopia"] = str(binary)
    repo = work / "repo"
    restore = work / "restore"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["KOPIA_PASSWORD"] = PILOT_PASSWORD
    env["KOPIA_CONFIG_PATH"] = str(work / "config.json")
    env["KOPIA_CACHE_DIRECTORY"] = str(work / "cache")
    env["KOPIA_LOG_DIR"] = str(work / "logs")
    env["KOPIA_CHECK_FOR_UPDATES"] = "false"
    steps = [
        ("repository create filesystem",
         [binary, "repository", "create", "filesystem",
          "--path", str(repo)]),
        ("snapshot create",
         [binary, "snapshot", "create", str(source)]),
        ("snapshot list", [binary, "snapshot", "list", "--json"]),
    ]
    snap_id = None
    for label, cmd in steps:
        proc = _run(cmd, env, evidence, label)
        if proc.returncode != 0:
            evidence["error"] = f"step failed: {label}"
            return evidence, 1
        if label == "snapshot list":
            try:
                snaps = json.loads(proc.stdout)
                snap_id = snaps[-1]["id"]
                evidence["snapshot_id"] = snap_id
            except Exception as exc:
                evidence["error"] = f"cannot parse snapshot list: {exc}"
                return evidence, 1
    proc = _run([binary, "restore", snap_id, str(restore)],
                env, evidence, "restore")
    if proc.returncode != 0:
        evidence["error"] = "step failed: restore"
        return evidence, 1
    src_hashes = sha256_tree(source)
    # Kopia restores the source under its own basename.
    restored_root = restore / source.name
    if not restored_root.is_dir():
        restored_root = restore
    dst_hashes = sha256_tree(restored_root)
    evidence["source_files"] = len(src_hashes)
    evidence["restored_files"] = len(dst_hashes)
    evidence["hashes_match"] = src_hashes == dst_hashes
    if src_hashes != dst_hashes:
        evidence["only_in_source"] = sorted(
            set(src_hashes) - set(dst_hashes))[:20]
        evidence["differing"] = sorted(
            k for k in set(src_hashes) & set(dst_hashes)
            if src_hashes[k] != dst_hashes[k])[:20]
        evidence["error"] = "restored hashes differ from source copy"
        return evidence, 1
    evidence["verified"] = True
    return evidence, 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Kopia pilot: snapshot a COPY, restore, verify.")
    ap.add_argument("command", choices=("run",))
    ap.add_argument("--source", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--kopia", default=None)
    ap.add_argument("--evidence", default=None)
    args = ap.parse_args(argv)
    evidence, code = pilot(args.source, args.work, args.kopia,
                           args.evidence)
    text = json.dumps(evidence, indent=2, ensure_ascii=False)
    if args.evidence:
        Path(args.evidence).write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"wiki_kopia_pilot: "
          f"{'RESTORE VERIFIED' if evidence['verified'] else 'NOT VERIFIED'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
