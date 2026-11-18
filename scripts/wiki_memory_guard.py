#!/usr/bin/env python3
"""Memory guard — refuse the changes that would quietly gut the wiki.

Pattern: the pre-commit guard of verified-memory-vault (MIT) —
file-count and removed-lines caps on mass deletion, refusal of
history rewrites, and graded exit codes with **2 = provenance
breach** — re-implemented for this wiki's surfaces and wired to
its own machinery (the erasure register of
scripts/wiki_erasure.py, the Black Box ledger of the gateway).

What it refuses:

  POLICY refusals (exit 1)
    - mass deletion of wiki pages: more than
      max(min_deleted_wiki_files,
          max_deleted_wiki_file_fraction x wiki pages at base)
      wiki/*.md files deleted (or renamed out of wiki/) in one
      change set;
    - mass line removal: more than
      max_removed_wiki_line_fraction of all wiki/*.md lines at
      base removed in one change set.

  PROVENANCE breaches (exit 2 — the graver class; if both
  classes fire, 2 is returned)
    - an existing file under raw/ MODIFIED. raw/ is immutable
      (AGENTS.md hard rule); two carve-outs, both anchored
      elsewhere: *manifest*.json bookkeeping files (regenerated
      by the provenance tooling, drift-checked by
      scripts/wiki_provenance.py --verify), and the agent-memory
      mirror subtree raw/sources/agent-memory/ (refreshed by
      design whenever the agent's memory changes; anchored by
      its own sha256 manifest + the same drift report);
    - a file under raw/ DELETED (or renamed away) without an
      erasure certificate in evaluation/erasure-certificates.jsonl
      whose scope names that path with the SHA-256 of the bytes
      being deleted. A forget must leave a receipt;
    - an append-only access ledger (wiki/access/*.jsonl — the
      Black Box) modified with lines removed, or deleted;
    - a non-fast-forward push (--pre-push mode): the remote
      head is not an ancestor of the pushed head, i.e. history
      is being rewritten.

Modes:
  --staged (default; the pre-commit hook mode)
      Inspect the index against HEAD.
  --range A..B
      Inspect a commit range (CI / audit use).
  --pre-push
      Read ref lines on stdin (the git pre-push protocol);
      per ref, check fast-forwardness, then the range checks.

Override: --override "<reason>" proceeds despite refusals and
records the act in the Black Box ledger (action
memory_guard_override, the reason as the direction source,
every refusal listed). There is no silent override: no flag,
no passage; an override always leaves a ledger entry. An
override on a clean change set writes nothing.

Thresholds live in DEFAULTS below — the one place — and can
be overridden per run with --config <json>.

Hook installation: --install-hooks writes .git/hooks/pre-commit
and .git/hooks/pre-push shims that call this script (refusing
to overwrite a foreign hook). Installation is a deliberate
local act and is NOT done by merely running the guard.

Stdlib only (plus the gateway ledger, imported in-process,
the same reuse scripts/wiki_evolve.py makes).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REGISTER_REL = "evaluation/erasure-certificates.jsonl"
MIRROR_SUBTREE = "raw/sources/agent-memory/"

# --- the one place thresholds live ---------------------------------------
DEFAULTS = {
    # Mass-deletion caps for wiki/*.md, measured against base.
    "max_deleted_wiki_file_fraction": 0.10,
    "min_deleted_wiki_files": 3,
    "max_removed_wiki_line_fraction": 0.20,
}
# -------------------------------------------------------------------------


def git(root: Path, *args, input_text=None):
    out = subprocess.run(["git", "-C", str(root), *args],
                         capture_output=True, text=True,
                         input=input_text, timeout=60)
    return out


def head_exists(root: Path) -> bool:
    return git(root, "rev-parse", "--verify", "HEAD").returncode == 0


def parse_name_status_z(text: str):
    """Parse `git diff --name-status -z` into (status, old, new) rows."""
    tokens = text.split("\0")
    rows = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        status = tok[0]
        if status in ("R", "C"):
            old, new = tokens[i + 1], tokens[i + 2]
            rows.append((status, old, new))
            i += 3
        else:
            rows.append((status, tokens[i + 1], tokens[i + 1]))
            i += 2
    return rows


def parse_numstat_z(text: str):
    """Parse `git diff --numstat -z` into {path: (added, deleted)}.

    Rename rows carry an empty path field followed by the old
    and new paths as separate tokens; lines are attributed to
    the NEW path.
    """
    tokens = text.split("\0")
    stats = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        parts = tok.split("\t")
        if len(parts) < 3:
            i += 1
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        if path == "":
            path = tokens[i + 2]  # rename: src, dst follow
            i += 3
        else:
            i += 1
        def num(v):
            return int(v) if v.isdigit() else 0
        stats[path] = (num(added), num(deleted))
    return stats


def get_changes(root: Path, base: str, target_args):
    """Return (rows, stats) for base -> target (index or a commit)."""
    ns = git(root, "diff", "--name-status", "-z", "-M", *target_args)
    nm = git(root, "diff", "--numstat", "-z", "-M", *target_args)
    if ns.returncode != 0:
        raise SystemExit(f"memory guard: git diff failed: {ns.stderr.strip()}")
    return parse_name_status_z(ns.stdout), parse_numstat_z(nm.stdout)


def wiki_stats_at(root: Path, base: str):
    """(page count, total lines) of wiki/*.md at the base ref."""
    out = git(root, "ls-tree", "-r", "--name-only", "-z", base, "--", "wiki/")
    if out.returncode != 0:
        return 0, 0
    paths = [p for p in out.stdout.split("\0") if p.endswith(".md")]
    total_lines = 0
    for p in paths:
        blob = git(root, "show", f"{base}:{p}")
        if blob.returncode == 0:
            data = blob.stdout.encode("utf-8", "surrogateescape")
            total_lines += data.count(b"\n") + (1 if data and
                                                 not data.endswith(b"\n")
                                                 else 0)
    return len(paths), total_lines


def blob_sha256(root: Path, base: str, path: str):
    import hashlib
    out = subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"],
                         capture_output=True, timeout=30)
    if out.returncode != 0:
        return None
    return hashlib.sha256(out.stdout).hexdigest()


def load_certificates(root: Path):
    """{path: sha256} from the erasure register ([] if absent)."""
    register = root / REGISTER_REL
    certs = {}
    if not register.exists():
        return certs
    with register.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cert = json.loads(line)
            for entry in cert.get("scope") or []:
                certs[entry["path"]] = entry["sha256"]
    return certs


def is_manifest_bookkeeping(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "manifest" in name and name.endswith(".json")


def check_changes(root: Path, base: str, rows, stats, cfg):
    """Return a list of refusals: {check, class, detail}."""
    refusals = []

    def refuse(check, cls, detail):
        refusals.append({"check": check, "class": cls, "detail": detail})

    # --- wiki mass deletion (policy) ---
    pages_at_base, lines_at_base = wiki_stats_at(root, base)
    wiki_deleted = []
    for status, old, new in rows:
        if status == "D":
            if old.startswith("wiki/") and old.endswith(".md"):
                wiki_deleted.append(old)
            if old.startswith("wiki/access/") and old.endswith(".jsonl"):
                refuse("ledger-deletion", "provenance",
                       f"append-only access ledger deleted: {old}")
        elif status == "R" and old != new:
            # renamed out of wiki/ counts as a deletion from wiki/;
            # renamed within wiki/ does not
            if old.startswith("wiki/") and old.endswith(".md") \
                    and not new.startswith("wiki/"):
                wiki_deleted.append(old)
    if pages_at_base:
        cap = max(cfg["min_deleted_wiki_files"],
                  int(cfg["max_deleted_wiki_file_fraction"] * pages_at_base))
        if len(wiki_deleted) > cap:
            refuse("mass-deletion-files", "policy",
                   f"{len(wiki_deleted)} wiki pages deleted in one change "
                   f"set; cap is {cap} "
                   f"({cfg['max_deleted_wiki_file_fraction']:.0%} of "
                   f"{pages_at_base} pages, floor "
                   f"{cfg['min_deleted_wiki_files']})")
    removed_lines = sum(d for p, (_a, d) in stats.items()
                        if p.startswith("wiki/") and p.endswith(".md"))
    if lines_at_base:
        cap_lines = cfg["max_removed_wiki_line_fraction"] * lines_at_base
        if removed_lines > cap_lines:
            refuse("mass-deletion-lines", "policy",
                   f"{removed_lines} wiki lines removed in one change "
                   f"set; cap is {int(cap_lines)} "
                   f"({cfg['max_removed_wiki_line_fraction']:.0%} of "
                   f"{lines_at_base} lines)")

    # --- raw/ integrity (provenance) ---
    certs = None  # loaded lazily, only if a raw removal appears
    for status, old, new in rows:
        path = old
        if not path.startswith("raw/"):
            continue
        if status == "M" or status == "T":
            if is_manifest_bookkeeping(path):
                continue
            if path.startswith(MIRROR_SUBTREE):
                continue
            refuse("raw-modification", "provenance",
                   f"existing raw file modified: {path} "
                   "(raw/ is immutable; add a new file instead)")
        elif status == "D" or (status == "R" and old != new):
            if certs is None:
                certs = load_certificates(root)
            digest = blob_sha256(root, base, path)
            if certs.get(path) is None:
                refuse("raw-deletion-uncertified", "provenance",
                       f"raw file removed without an erasure "
                       f"certificate: {path} (issue one with "
                       "scripts/wiki_erasure.py issue)")
            elif digest is not None and certs[path] != digest:
                refuse("raw-deletion-uncertified", "provenance",
                       f"erasure certificate for {path} names "
                       "different bytes than the ones being deleted")

    # --- access-ledger truncation (provenance) ---
    for status, old, new in rows:
        if status == "M" and old.startswith("wiki/access/") \
                and old.endswith(".jsonl"):
            _a, deleted = stats.get(old, (0, 0))
            if deleted > 0:
                refuse("ledger-truncation", "provenance",
                       f"append-only ledger {old} loses {deleted} "
                       "line(s) in this change")
    return refusals


def record_override(root: Path, actor: str, reason: str,
                    refusals, rows):
    """Append the override to the Black Box ledger. Returns entry id."""
    sys.path.insert(0, str(root / "tools" / "gateway"))
    from gateway.ledger import Ledger  # noqa: E402

    access = root / "wiki" / "access"
    ledgers = sorted(access.glob("black-box-*.jsonl"))
    if ledgers:
        ledger_path = ledgers[-1]
    else:
        from datetime import datetime
        ledger_path = access / f"black-box-{datetime.now().year}.jsonl"
    ledger = Ledger(ledger_path, id_prefix="bb", wiki_root=root)
    paths = sorted({p for _s, o, n in rows for p in (o, n)})
    entry = ledger.append({
        "schema_version": "blackbox/1",
        "actor": actor,
        "auth_method": "cli-override-flag",
        "client": "wiki_memory_guard",
        "session_id": "memory-guard",
        "task_ref": None,
        "direction_source": {"kind": "guard-override", "ref": reason},
        "action": "memory_guard_override",
        "tool": "wiki_memory_guard",
        "files_read": [],
        "files_written": paths,
        "result": "allow",
        "commit_shas": [],
        "guard_refusals": refusals,
    })
    return entry["entry_id"]


def verdict(root: Path, cfg, rows, stats, base, args) -> int:
    refusals = check_changes(root, base, rows, stats, cfg)
    changed = len({p for _s, o, n in rows for p in (o, n)})
    if not refusals:
        print(f"memory guard: PASS ({changed} path(s) in change set)")
        return 0
    worst = 1
    for r in refusals:
        if r["class"] == "provenance":
            worst = 2
        print(f"memory guard: REFUSED [{r['class']}] {r['check']}: "
              f"{r['detail']}")
    if args.override:
        entry_id = record_override(root, args.actor, args.override,
                                   refusals, rows)
        print(f"memory guard: OVERRIDDEN by {args.actor} — recorded "
              f"in the Black Box ledger as {entry_id} "
              f"(reason: {args.override})")
        return 0
    print("memory guard: change set refused. A deliberate override "
          "is possible with --override \"<reason>\" and is recorded "
          "in the Black Box ledger.")
    return worst


def install_hooks(root: Path) -> int:
    hooks = root / ".git" / "hooks"
    if not hooks.parent.exists():
        print("memory guard: no .git directory — cannot install hooks")
        return 2
    hooks.mkdir(exist_ok=True)
    script = root / "scripts" / "wiki_memory_guard.py"
    wanted = {
        "pre-commit": f'#!/bin/sh\nexec python3 "{script}" --staged\n',
        "pre-push": f'#!/bin/sh\nexec python3 "{script}" --pre-push\n',
    }
    for name, content in wanted.items():
        target = hooks / name
        if target.exists():
            if target.read_text(encoding="utf-8") == content:
                print(f"  {name}: already installed")
                continue
            print(f"  {name}: EXISTS with different content — "
                  "not overwritten; merge by hand")
            return 1
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
        print(f"  {name}: installed")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Refuse change sets that would gut the wiki's "
                    "memory surfaces (see module docstring).")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true",
                      help="inspect the index against HEAD (default; "
                           "the pre-commit hook mode)")
    mode.add_argument("--range", dest="range", default=None,
                      metavar="A..B", help="inspect a commit range")
    mode.add_argument("--pre-push", action="store_true",
                      help="read ref lines on stdin (git pre-push "
                           "protocol)")
    mode.add_argument("--install-hooks", action="store_true",
                      help="install .git/hooks shims and exit")
    ap.add_argument("--override", default=None, metavar="REASON",
                    help="proceed despite refusals; recorded in the "
                         "Black Box ledger")
    ap.add_argument("--actor", default="agent",
                    help="actor name for the override record")
    ap.add_argument("--config", default=None,
                    help="JSON file overriding DEFAULTS thresholds")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else ROOT
    cfg = dict(DEFAULTS)
    if args.config:
        cfg.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    if args.install_hooks:
        return install_hooks(root)

    if args.pre_push:
        worst = 0
        lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
        if not lines:
            print("memory guard: PASS (no refs pushed)")
            return 0
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4:
                continue
            _lref, local_sha, _rref, remote_sha = parts[:4]
            zeros = "0" * 40
            if local_sha == zeros:
                print(f"memory guard: ref deletion ({_lref}) — no "
                      "content checks apply")
                continue
            if remote_sha != zeros:
                anc = git(root, "merge-base", "--is-ancestor",
                          remote_sha, local_sha)
                if anc.returncode != 0:
                    refusal = {"check": "history-rewrite",
                               "class": "provenance",
                               "detail": f"push to {_lref} is not a "
                                         "fast-forward: remote head "
                                         f"{remote_sha[:12]} is not an "
                                         "ancestor of "
                                         f"{local_sha[:12]}"}
                    print(f"memory guard: REFUSED [provenance] "
                          f"history-rewrite: {refusal['detail']}")
                    if args.override:
                        entry_id = record_override(
                            root, args.actor, args.override, [refusal], [])
                        print(f"memory guard: OVERRIDDEN — recorded "
                              f"as {entry_id}")
                        continue
                    worst = 2
                    continue
                base, rng = remote_sha, [f"{remote_sha}..{local_sha}"]
            else:
                base, rng = EMPTY_TREE, [local_sha]
            rows, stats = get_changes(root, base, rng)
            rc = verdict(root, cfg, rows, stats, base, args)
            worst = max(worst, rc)
        return worst

    if args.range:
        if ".." not in args.range:
            print("memory guard: --range needs A..B")
            return 2
        base = args.range.split("..", 1)[0] or EMPTY_TREE
        rows, stats = get_changes(root, base, [args.range])
        return verdict(root, cfg, rows, stats, base, args)

    # default: staged
    base = "HEAD" if head_exists(root) else EMPTY_TREE
    target = ["--cached"] + ([] if head_exists(root) else [EMPTY_TREE])
    rows, stats = get_changes(root, base, target)
    return verdict(root, cfg, rows, stats, base, args)


if __name__ == "__main__":
    raise SystemExit(main())
