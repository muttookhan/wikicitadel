#!/usr/bin/env python3
"""Sandboxed verification-script runner (E2B pattern, scoped form).

Implements Marathon Round 3 TB8 row 3, from the E2B find in
raw/sources/2026-10-20-global-landscape/r2-europe-india-academic-finds.md:
agent-generated verification/audit scripts run inside a disposable
sandbox rather than on the host, with the transcript kept as
provenance. E2B itself is a cloud sandbox service (Apache-2.0);
nothing of it is copied or called — this is the local, stdlib-only
scoped form of the pattern.

What the sandbox DOES enforce (stdlib process isolation):
  * the script runs as a child process with its cwd set to a fresh
    temporary directory (kept afterwards only if --keep-workdir);
  * the environment is SCRUBBED: the child receives only PATH,
    LANG/LC_ALL (passed through if set), and SANDBOX=1 — no tokens,
    no home config, nothing else the parent had;
  * a wall-clock timeout (default 30s) — a script that overruns is
    killed and the overrun is reported as a violation;
  * POSIX resource limits via preexec: CPU seconds, address space
    (--memory-mb, default 512), file size, and open files;
  * captured stdout/stderr are truncated at a stated byte cap.

What it does NOT enforce — stated honestly, because a sandbox that
overstates itself is worse than none:
  * NETWORK: stdlib process isolation cannot reliably block
    network access portably. If the Linux `unshare` tool is
    present, the runner uses `unshare -n` for a private network
    namespace and reports network_isolation="unshare-n"; otherwise
    it reports network_isolation="none" and the run's JSON carries
    the limit on its face. Do not run a script whose network use
    you cannot tolerate on a host without `unshare`.
  * FILESYSTEM: the child can READ anything the invoking user can
    read, and can write outside its temp cwd if paths are
    absolute. The temp cwd confines RELATIVE writes only; this is
    best-effort isolation, not a security boundary against a
    hostile script. It is a seatbelt for our own verification
    scripts, not a jail for adversarial code.
  * Limits are POSIX-only; on a non-POSIX host the runner refuses
    to pretend and reports limits_applied=false.

Usage:
  python3 scripts/wiki_sandbox_run.py path/to/check.py [-- arg...]
  python3 scripts/wiki_sandbox_run.py check.py --timeout 10 --json

Exit codes: 0 = script ran clean (exit 0, no violations);
3 = violations (timeout / resource kill / output cap) or the
script itself exited non-zero; 2 = usage / runner error.
Stdlib only.
"""
import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUTPUT_CAP = 200_000


def scrubbed_env():
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "SANDBOX": "1"}
    for key in ("LANG", "LC_ALL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _limits(timeout_s, memory_mb, file_mb):
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU,
                           (max(1, int(timeout_s) + 1),
                            max(1, int(timeout_s) + 2)))
        resource.setrlimit(resource.RLIMIT_AS,
                           (memory_mb * 1024 * 1024,
                            memory_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE,
                           (file_mb * 1024 * 1024,
                            file_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    return apply


def run_sandboxed(script, script_args=(), timeout=30, memory_mb=512,
                  file_mb=16, keep_workdir=False):
    """Run one script under the sandbox constraints. Returns the
    report dict (see module docstring for what each field means;
    `limits` states the sandbox's limits on its face)."""
    script = Path(script)
    report = {
        "script": str(script),
        "constraints": {
            "cwd": "fresh temp dir",
            "env": "scrubbed (PATH, LANG/LC_ALL, SANDBOX=1)",
            "timeout_s": timeout,
            "memory_mb": memory_mb,
            "file_mb": file_mb,
            "network_isolation": "none",
            "limits_applied": False,
        },
        "limits": [
            "best-effort process isolation via stdlib only — NOT "
            "a security boundary against hostile code",
            "filesystem: relative writes confined to the temp cwd; "
            "absolute-path reads/writes are not blocked",
            "network: blocked only when network_isolation is "
            "unshare-n; otherwise NOT blocked",
        ],
        "violations": [],
        "exit_code": None,
        "timed_out": False,
        "duration_s": None,
        "stdout": "",
        "stderr": "",
        "produced_files": [],
    }
    if not script.is_file():
        report["violations"].append(f"script not found: {script}")
        return report
    cmd = [sys.executable, str(script.resolve()),
           *[str(a) for a in script_args]]
    unshare = shutil.which("unshare")
    if unshare:
        cmd = [unshare, "-n", *cmd]
        report["constraints"]["network_isolation"] = "unshare-n"
    workdir = Path(tempfile.mkdtemp(prefix="wiki-sandbox-"))
    preexec = None
    if os.name == "posix":
        preexec = _limits(timeout, memory_mb, file_mb)
        report["constraints"]["limits_applied"] = True
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, env=scrubbed_env(),
            capture_output=True, text=True, timeout=timeout,
            preexec_fn=preexec)
        report["exit_code"] = proc.returncode
        report["stdout"] = proc.stdout[:OUTPUT_CAP]
        report["stderr"] = proc.stderr[:OUTPUT_CAP]
        if len(proc.stdout) > OUTPUT_CAP or \
                len(proc.stderr) > OUTPUT_CAP:
            report["violations"].append(
                "output exceeded the capture cap and was truncated")
        if proc.returncode not in (0, None):
            if proc.returncode < 0:
                report["violations"].append(
                    f"killed by signal {-proc.returncode} "
                    "(resource limit or external kill)")
            else:
                report["violations"].append(
                    f"script exited non-zero: {proc.returncode}")
    except subprocess.TimeoutExpired as exc:
        report["timed_out"] = True
        report["violations"].append(
            f"timeout: script exceeded {timeout}s and was killed")
        report["stdout"] = (exc.stdout or b"").decode(
            "utf-8", "replace")[:OUTPUT_CAP] \
            if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        report["stderr"] = (exc.stderr or b"").decode(
            "utf-8", "replace")[:OUTPUT_CAP] \
            if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    report["duration_s"] = round(time.monotonic() - start, 3)
    report["produced_files"] = sorted(
        str(p.relative_to(workdir))
        for p in workdir.rglob("*") if p.is_file())
    if keep_workdir:
        report["workdir"] = str(workdir)
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("script", help="python script to run sandboxed")
    ap.add_argument("script_args", nargs="*", help="args after --")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--memory-mb", type=int, default=512)
    ap.add_argument("--file-mb", type=int, default=16)
    ap.add_argument("--keep-workdir", action="store_true")
    ap.add_argument("--json", action="store_true",
                    help="print the report as JSON (the default "
                         "when stdout is not a TTY is JSON anyway)")
    args = ap.parse_args(argv)
    script_args = args.script_args
    if script_args and script_args[0] == "--":
        script_args = script_args[1:]
    if not Path(args.script).is_file():
        print(f"sandbox: no such script: {args.script}",
              file=sys.stderr)
        return 2
    report = run_sandboxed(args.script, script_args,
                           timeout=args.timeout,
                           memory_mb=args.memory_mb,
                           file_mb=args.file_mb,
                           keep_workdir=args.keep_workdir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["violations"] else 3


if __name__ == "__main__":
    sys.exit(main())
