#!/usr/bin/env python3
"""Deterministic hooks around the agent loop (Marathon R3,
Tier B row TB3-2; Haystack pattern).

Pattern: Haystack's pipeline hooks — named, deterministic
checks that run around a pipeline step, declared as DATA
rather than buried in code, with a hard halt on failure.
Re-implemented from the idea in this wiki's register style;
no code copied.

The register is evaluation/hooks.jsonl, one hook per line:

    {"hook_id": "h-abstention-before-promote",
     "step": "promote", "phase": "pre",     # pre | post
     "check": {"kind": "command", "argv": ["python3",
               "scripts/wiki_abstention_check.py"]},
     "on_fail": "halt"}

Check kinds (all deterministic, all local):
  command       run argv (no shell); passes on exit 0
  file-exists   {"kind": "file-exists", "path": rel}
  file-absent   {"kind": "file-absent", "path": rel}
  sha256        {"kind": "sha256", "path": rel, "equals": hex}
  json-field    {"kind": "json-field", "path": rel,
                 "field": name, "equals": value}

The runner executes a step's hooks in register order —
pre hooks, then the step itself, then post hooks — and
HALTS on the first failing hook: the step does not run
when a pre hook fails, and a failing post hook fails the
whole stage (exit 1) with the hook named. Nothing is
retried, reordered, or skipped silently.

Usage:
  python3 scripts/wiki_hooks.py add HOOK.json
  python3 scripts/wiki_hooks.py list [--step STEP]
  python3 scripts/wiki_hooks.py run --step STEP -- CMD...

Exit codes: run 0 = stage + all hooks passed, 1 = a hook
(or the stage command) failed and the pipeline halted,
2 = usage error. Stdlib only; hooks never call the network
themselves (a command hook runs exactly what is declared).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER_REL = "evaluation/hooks.jsonl"


def load_hooks(root: Path):
    path = root / REGISTER_REL
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_check(root: Path, check: dict):
    """(passed, detail) for one declared check."""
    kind = check.get("kind")
    if kind == "command":
        argv = check.get("argv") or []
        if not argv:
            return False, "empty argv"
        r = subprocess.run(argv, cwd=str(root), capture_output=True,
                           text=True, timeout=600)
        return r.returncode == 0, f"exit {r.returncode}"
    if kind in ("file-exists", "file-absent", "sha256", "json-field"):
        p = root / check.get("path", "")
        if kind == "file-exists":
            return p.is_file(), f"{check.get('path')} exists={p.is_file()}"
        if kind == "file-absent":
            return not p.exists(), f"{check.get('path')} absent={not p.exists()}"
        if not p.is_file():
            return False, f"{check.get('path')} missing"
        if kind == "sha256":
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            return got == check.get("equals"), f"sha256 {got[:12]}…"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return False, f"not JSON: {exc}"
        got = data.get(check.get("field"))
        return got == check.get("equals"), f"{check.get('field')}={got!r}"
    return False, f"unknown check kind {kind!r}"


def run_hooks(root: Path, step: str, phase: str):
    """Run one phase's hooks for a step, in register order.
    Returns (ok, results) — stops at the first failure."""
    results = []
    for hook in load_hooks(root):
        if hook.get("step") != step or hook.get("phase") != phase:
            continue
        passed, detail = run_check(root, hook.get("check") or {})
        results.append({"hook_id": hook.get("hook_id"), "phase": phase,
                        "passed": passed, "detail": detail})
        if not passed:
            return False, results
    return True, results


def run_stage(root: Path, step: str, stage_fn):
    """The full staged step: pre hooks -> stage_fn -> post
    hooks, halting on any failure. stage_fn() returns an
    exit-code-like int (0 = ok). Returns (exit_code, report)."""
    report = {"step": step, "hooks": [], "stage_ran": False}
    ok, res = run_hooks(root, step, "pre")
    report["hooks"] += res
    if not ok:
        report["halted"] = "pre-hook failure; stage not run"
        return 1, report
    report["stage_ran"] = True
    code = stage_fn()
    report["stage_exit"] = code
    if code != 0:
        report["halted"] = "stage command failed; post hooks not run"
        return 1, report
    ok, res = run_hooks(root, step, "post")
    report["hooks"] += res
    if not ok:
        report["halted"] = "post-hook failure"
        return 1, report
    return 0, report


def cmd_add(root: Path, spec_path: Path):
    try:
        hook = json.loads(spec_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"cannot read hook spec: {exc}", file=sys.stderr)
        return 2
    for field in ("hook_id", "step", "phase", "check"):
        if field not in hook:
            print(f"hook spec missing {field!r}", file=sys.stderr)
            return 2
    if hook["phase"] not in ("pre", "post"):
        print("phase must be 'pre' or 'post'", file=sys.stderr)
        return 2
    reg = root / REGISTER_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    with reg.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(hook, sort_keys=True) + "\n")
    print(f"hook {hook['hook_id']} registered "
          f"({hook['phase']} {hook['step']})")
    return 0


def cmd_list(root: Path, step):
    hooks = load_hooks(root)
    if step:
        hooks = [h for h in hooks if h.get("step") == step]
    print(json.dumps({"hooks": hooks}, indent=2, sort_keys=True))
    return 0


def cmd_run(root: Path, step: str, cmd):
    if not cmd:
        print("run needs -- CMD...", file=sys.stderr)
        return 2

    def stage():
        return subprocess.run(cmd, cwd=str(root)).returncode

    code, report = run_stage(root, step, stage)
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add", help="register a hook from a JSON spec")
    pa.add_argument("spec")
    pl = sub.add_parser("list", help="list registered hooks")
    pl.add_argument("--step", default=None)
    pr = sub.add_parser("run", help="run a staged step under its hooks")
    pr.add_argument("--step", required=True)
    pr.add_argument("stage_cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    if args.cmd == "add":
        return cmd_add(root, Path(args.spec))
    if args.cmd == "list":
        return cmd_list(root, args.step)
    cmd = args.stage_cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    return cmd_run(root, args.step, cmd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
