#!/usr/bin/env python3
"""Git sync helper for a wiki repository (gap 11, scoped form).

Wraps the custody discipline in one tool: pull before work, push on
integration, and NEVER resolve a divergence or a conflict silently.
Real-time co-editing is deliberately out of scope — git remains the
sync layer; this tool makes its state legible and its failures loud.

Subcommands:
  status            branch, ahead/behind vs the remote, dirty files,
                    and any conflicted paths (exit 1 if conflicted)
  pull              fetch + fast-forward only; a diverged branch is
                    reported, never merged or rebased (exit 2)
  push              push the current branch (refuses while conflicted)
  sync              pull, then push

Stdlib only. All git output is passed through; nothing is hidden.
"""
import argparse
import subprocess
import sys
from pathlib import Path


def git(root, *args, check=False):
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r


def conflicted_paths(root):
    """Paths with unmerged entries, from git status porcelain."""
    r = git(root, "status", "--porcelain")
    out = []
    for line in r.stdout.splitlines():
        code = line[:2]
        if "U" in code or code in ("AA", "DD"):
            out.append(line[3:].strip())
    return out


def sync_state(root, remote="origin"):
    """Return a dict describing branch/ahead/behind/conflict state."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git(root, "fetch", remote)
    counts = git(root, "rev-list", "--left-right", "--count",
                 f"HEAD...{remote}/{branch}").stdout.split()
    ahead = int(counts[0]) if len(counts) == 2 else 0
    behind = int(counts[1]) if len(counts) == 2 else 0
    dirty = [ln[3:].strip() for ln in
             git(root, "status", "--porcelain").stdout.splitlines() if ln.strip()]
    return {"branch": branch, "ahead": ahead, "behind": behind,
            "dirty": dirty, "conflicts": conflicted_paths(root)}


def cmd_status(root, remote):
    st = sync_state(root, remote)
    print(f"branch: {st['branch']}  ahead: {st['ahead']}  behind: {st['behind']}")
    if st["dirty"]:
        print(f"dirty files: {len(st['dirty'])}")
    if st["conflicts"]:
        print("CONFLICTED (resolve by hand; this tool never auto-resolves):")
        for p in st["conflicts"]:
            print(f"  {p}")
        return 1
    print("no conflicts")
    return 0


def cmd_pull(root, remote):
    st = sync_state(root, remote)
    if st["conflicts"]:
        print("refusing to pull: unresolved conflicts present", file=sys.stderr)
        return 1
    if st["ahead"] and st["behind"]:
        print(f"DIVERGED: local is {st['ahead']} ahead and {st['behind']} behind "
              f"{remote}/{st['branch']}. No merge or rebase attempted — "
              "reconcile by hand.", file=sys.stderr)
        return 2
    if st["behind"] == 0:
        print("already up to date")
        return 0
    r = git(root, "merge", "--ff-only", f"{remote}/{st['branch']}")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_push(root, remote):
    if conflicted_paths(root):
        print("refusing to push: unresolved conflicts present", file=sys.stderr)
        return 1
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    r = git(root, "push", remote, branch)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["status", "pull", "push", "sync"])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--remote", default="origin")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.command == "status":
        return cmd_status(root, args.remote)
    if args.command == "pull":
        return cmd_pull(root, args.remote)
    if args.command == "push":
        return cmd_push(root, args.remote)
    rc = cmd_pull(root, args.remote)
    if rc != 0:
        return rc
    return cmd_push(root, args.remote)


if __name__ == "__main__":
    sys.exit(main())
