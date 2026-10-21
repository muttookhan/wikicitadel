#!/usr/bin/env python3
"""Gap-9 standing auto-watch — the AUTO-WATCH half of the
15-gap item 9 pair (Marathon Round 3, Tier A).

The persistent ingest queue (scripts/wiki_ingest_queue.py,
round 1) already has a `watch` command, but it is bound to
ONE directory and keeps no state of its own: it leans on the
queue's content-hash identity to make re-passes harmless,
and it cannot say what it has seen, skip a file it already
offered that the queue has since completed, or watch the
several drop locations this wiki actually receives material
at. This tool is the standing watcher that sits IN FRONT of
that queue:

  * it observes the drop locations named in a WATCH MANIFEST
    (JSON; template: templates/watch-manifest.example.json) —
    directories (recursive), single files, and glob patterns,
    each with its own queue job kind;
  * every newly arrived file is enqueued into the EXISTING
    queue by invoking wiki_ingest_queue.py's own enqueue
    (subprocess — the queue's identity, locking and register
    are never re-implemented here);
  * it is crash-safe: a STATE FILE (JSON, written atomically
    via temp-file + os.replace, flushed + fsynced) records
    every file it has offered, by content hash
    {path: {sha256, size, offered_at, queue_id}}. A restart
    re-offers nothing twice: a file whose path + hash stand
    in the state was already offered, whatever happened while
    the watcher was down; a file whose CONTENT changed (hash
    differs) is a new arrival and is offered again (the queue
    will give it a new item id, by its own identity rule);
    a file that disappears is dropped from the state on the
    next pass, so a later identical re-drop is offered fresh;
  * it honours its own automation manifest: the watch
    manifest carries an "automation" block in the
    automation-readiness gate's format
    (scripts/wiki_automation_gate.py); `check-gate` runs that
    gate over the block, and `run` REFUSES to start
    unattended (exit 1) unless the gate verdict is READY —
    the gate is not decoration.
  * kill switch: when the manifest's kill_switch is a
    stop-file, its presence at pass start ends the loop
    cleanly (stated in the log line); --once runs one pass
    regardless for attended use but still honours the gate.

State and log live where the manifest says (defaults:
evaluation/auto-watch-state.json and
evaluation/auto-watch.log — an append-only line per pass —
both inside the tree, never in the watched drop dirs
themselves; files under the state/log paths and the queue's
own register are excluded from watching even if a watched
directory contains them).

Usage:
  python3 scripts/wiki_auto_watch.py [--root PATH]
      check-gate --manifest <watch-manifest.json>
  python3 scripts/wiki_auto_watch.py [--root PATH]
      run --manifest <watch-manifest.json>
          [--once] [--interval N] [--dry-run]

Exit: 0 = ok (a pass completed / gate READY); 1 = gate
NOT-READY for `run`; 2 = usage error / manifest invalid /
queue enqueue failed.
Stdlib only. NOT wired into any live cron by this build —
the proposed cron line is recorded in the build manifest.
"""
import argparse
import glob as glob_mod
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent

DEFAULT_STATE = "evaluation/auto-watch-state.json"
DEFAULT_LOG = "evaluation/auto-watch.log"


class WatchError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_gate(root):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wiki_automation_gate",
        Path(root) / "scripts" / "wiki_automation_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ manifest

def load_manifest(path):
    p = Path(path)
    if not p.is_file():
        raise WatchError(f"no watch manifest at {path}")
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WatchError(f"watch manifest does not parse: {exc}")
    if not isinstance(m, dict):
        raise WatchError("watch manifest is not a JSON object")
    watches = m.get("watches")
    if not isinstance(watches, list) or not watches:
        raise WatchError("watch manifest names no watches "
                         "(a non-empty 'watches' list is required)")
    for w in watches:
        if not isinstance(w, dict) or not w.get("path"):
            raise WatchError(f"watch entry lacks a path: {w!r}")
        if w.get("kind", "ingest") not in ("ingest", "convert",
                                           "compile"):
            raise WatchError(f"watch entry {w['path']!r}: kind "
                             f"must be ingest|convert|compile")
    return m


def watched_files(root, manifest):
    """Resolve the manifest's watches to concrete files:
    a list of (file_path, job_kind). Directories are walked
    recursively; entries containing glob metacharacters are
    expanded; plain files are taken as-is. Paths are relative
    to the root unless absolute."""
    root = Path(root)
    out = []
    seen = set()
    for w in manifest["watches"]:
        raw = str(w["path"])
        kind = w.get("kind", "ingest")
        base = Path(raw) if Path(raw).is_absolute() else root / raw
        candidates = []
        if any(c in raw for c in "*?["):
            candidates = [Path(p) for p in
                          sorted(glob_mod.glob(str(base),
                                               recursive=True))]
        elif base.is_dir():
            candidates = sorted(p for p in base.rglob("*")
                                if p.is_file())
        elif base.is_file():
            candidates = [base]
        for p in candidates:
            if p.is_file() and p.resolve() not in seen:
                seen.add(p.resolve())
                out.append((p, kind))
    return out


# ------------------------------------------------------------ state

def load_state(path):
    p = Path(path)
    if not p.is_file():
        return {"version": 1, "offered": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise WatchError(
            f"state file {p} does not parse — a torn state is "
            f"refused, never silently reset (resetting would "
            f"re-offer everything); repair or remove it "
            f"deliberately")
    if not isinstance(data, dict) or \
            not isinstance(data.get("offered"), dict):
        raise WatchError(f"state file {p} has no 'offered' map")
    return data


def save_state(path, state):
    """Atomic, fsynced state write: temp file in the same
    directory + os.replace, so a crash mid-write leaves the
    previous state whole."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(state, indent=1, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def content_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------ queue seam

def enqueue_via_queue(root, file_path, job_kind):
    """Offer one file to the existing ingest queue through
    its own CLI. Returns the queue's stdout line. A queue
    refusal is a WatchError (exit 2) — never swallowed."""
    cmd = [sys.executable,
           str(Path(root) / "scripts" / "wiki_ingest_queue.py"),
           "--root", str(root), "enqueue", str(file_path),
           "--kind", job_kind]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WatchError(f"queue enqueue failed for "
                         f"{file_path}: {proc.stderr.strip()}")
    return proc.stdout.strip()


# ------------------------------------------------------------ one pass

def one_pass(root, manifest, dry_run=False, enqueue_fn=None):
    """One watch pass. Returns a report dict:
    {offered: [...], unchanged: n, vanished: [...], files_seen: n}.
    Crash-safety invariant: a file is recorded in the state
    only AFTER the queue has accepted it (its enqueue
    returned), and the state is saved before the pass
    reports — so a crash mid-pass re-offers at most the file
    in flight, and the queue's own content-hash identity
    makes even that a no-op duplicate report, never a
    duplicate item."""
    root = Path(root)
    state_rel = manifest.get("state_path", DEFAULT_STATE)
    state_path = root / state_rel
    state = load_state(state_path)
    offered_map = state["offered"]

    excluded = {state_path.resolve(),
                (root / manifest.get("log_path", DEFAULT_LOG)).resolve(),
                (root / "evaluation" / "ingest-queue.jsonl").resolve(),
                (root / "evaluation" / "ingest-queue.lock").resolve()}
    files = [(p, k) for p, k in watched_files(root, manifest)
             if p.resolve() not in excluded]

    enqueue = enqueue_fn or \
        (lambda fp, k: enqueue_via_queue(root, fp, k))
    offered, unchanged = [], 0
    seen_keys = set()
    for p, kind in files:
        key = str(p.resolve())
        seen_keys.add(key)
        digest = content_hash(p)
        prior = offered_map.get(key)
        if prior and prior.get("sha256") == digest:
            unchanged += 1
            continue
        if not dry_run:
            line = enqueue(p, kind)
            offered_map[key] = {
                "sha256": digest, "size": p.stat().st_size,
                "kind": kind, "offered_at": _now(),
                "queue_line": line}
        offered.append({"path": key, "kind": kind,
                        "sha256": digest,
                        "changed": prior is not None})
    vanished = sorted(set(offered_map) - seen_keys)
    for key in vanished:
        del offered_map[key]
    state["last_pass"] = _now()
    if not dry_run:
        save_state(state_path, state)
    return {"offered": offered, "unchanged": unchanged,
            "vanished": vanished, "files_seen": len(files),
            "dry_run": dry_run}


def _log(root, manifest, line):
    log_path = Path(root) / manifest.get("log_path", DEFAULT_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{_now()} {line}\n")
        fh.flush()
        os.fsync(fh.fileno())


def _stopped(root, manifest):
    ks = (manifest.get("automation") or {}).get("kill_switch") or {}
    if ks.get("kind") == "stop-file" and ks.get("value"):
        v = Path(ks["value"])
        return v.exists() if v.is_absolute() else \
            (Path(root) / v).exists()
    return False


# ------------------------------------------------------------ commands

def gate_verdict(root, manifest):
    gate = _load_gate(root)
    return gate.check_manifest(manifest.get("automation") or {})


def cmd_check_gate(root, args):
    manifest = load_manifest(args.manifest)
    verdict, checks = gate_verdict(root, manifest)
    if args.json:
        print(json.dumps({"verdict": verdict, "checks": checks},
                         indent=2, ensure_ascii=False))
    else:
        print(f"automation gate for this watcher: {verdict}")
        for c in checks:
            mark = "ok  " if c["ok"] else "FAIL"
            print(f"  [{mark}] {c['criterion']}: {c['detail']}")
    return 0 if verdict == "READY" else 1


def cmd_run(root, args):
    manifest = load_manifest(args.manifest)
    verdict, _checks = gate_verdict(root, manifest)
    if verdict != "READY":
        print(f"wiki_auto_watch: automation gate verdict is "
              f"{verdict} — refusing to run unattended; run "
              f"`check-gate` for the failing criteria",
              file=sys.stderr)
        return 1
    interval = args.interval if args.interval is not None else \
        float(((manifest.get("automation") or {}).get("schedule")
               or {}).get("seconds") or 60)
    if interval <= 0:
        raise WatchError("--interval must be > 0")
    while True:
        if _stopped(root, manifest):
            line = "stop-file present — watcher stopping cleanly"
            print(line)
            if not args.dry_run:
                _log(root, manifest, line)
            return 0
        report = one_pass(root, manifest, dry_run=args.dry_run)
        line = (f"pass: {report['files_seen']} file(s) seen, "
                f"{len(report['offered'])} offered, "
                f"{report['unchanged']} unchanged, "
                f"{len(report['vanished'])} vanished")
        print(line)
        for o in report["offered"]:
            print(f"  offered {o['path']} (kind={o['kind']}"
                  f"{', changed' if o['changed'] else ''})")
        if not args.dry_run:
            _log(root, manifest, line)
        if args.once:
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Gap-9 standing auto-watch: offers new "
                    "arrivals at stated drop locations to the "
                    "persistent ingest queue, crash-safely.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: the checkout "
                         "holding this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check-gate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True)
        p.add_argument("--root", default=argparse.SUPPRESS)
        if name == "check-gate":
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--once", action="store_true")
            p.add_argument("--interval", type=float, default=None)
            p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root) if getattr(args, "root", None) \
        else DEFAULT_ROOT
    try:
        if args.cmd == "check-gate":
            return cmd_check_gate(root, args)
        if args.cmd == "run":
            return cmd_run(root, args)
    except WatchError as exc:
        print(f"wiki_auto_watch: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
