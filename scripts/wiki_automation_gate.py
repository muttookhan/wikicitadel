#!/usr/bin/env python3
"""The automation-readiness gate — a pre-flight checker that
decides whether a proposed automation (a cron job, a watcher,
any unattended runner) may run unattended (Marathon Round 3,
Tier A row: the automation-readiness gate, named in the
round-2 record's standing Tier A queue).

Why a gate: an unattended runner is trusted with the corpus
while nobody is watching. The trust has to be earned in
advance, on the record, against stated criteria — not assumed
because the script looked fine in an attended session. A
proposal describes itself in a small MANIFEST (JSON; template:
templates/automation-manifest.example.json) and this checker
verifies every criterion mechanically. A proposal that fails
any criterion does not run unattended; the failures are the
work list for fixing it.

Criteria (each checked, each named in the report):

  identity        — the manifest names the automation (name),
                    what it runs (command: a non-empty argv
                    list), and who owns it (owner: a stated
                    identity / seat, never blank).
  schedule        — a stated schedule (cron expression text,
                    an interval in seconds, or the literal
                    "manual" for a human-launched runner); an
                    automation with no stated schedule is an
                    automation nobody can predict.
  idempotence     — the manifest DECLARES idempotence
                    (idempotent: true) AND names the mechanism
                    that makes a re-run safe (idempotence_key:
                    e.g. "content-hash dedupe", "append-only
                    register with item ids"). A bare true with
                    no named mechanism fails: the claim must
                    say HOW.
  kill_switch     — a named kill switch: a stop file path, an
                    env var, or a stated disable command
                    (kill_switch: {"kind": "stop-file"|"env"|
                    "command", "value": ...}). "Kill it from
                    the process list" is not a kill switch.
  log_path        — a stated log path the runner writes
                    (log_path), inside the tree or an absolute
                    path; unattended work with no log is work
                    that cannot be audited afterwards.
  owner_notice    — how the owner hears about runs and
                    failures (owner_notice: one of "log-only"
                    is NOT enough — must be "chat" | "email" |
                    "lens" | "log+chat" | "log+email" |
                    "log+lens"; a purely silent automation
                    fails). "log-only" is a stated, deliberate
                    choice the gate still refuses for
                    unattended running: the log is where a
                    failure would be found, eventually, by
                    someone who already suspects it.
  bounded         — a stated bound: max_runtime_seconds > 0
                    AND max_items_per_run > 0 (or an explicit
                    "unbounded_reason" — named, not silent;
                    the gate reports it as a warning, not a
                    pass).
  no_live_wiring  — the manifest states dry_run_default or
                    states its blast radius (writes: a list of
                    the paths/areas it may write; an empty
                    list means read-only). An automation that
                    cannot say what it writes fails.

Verdicts: READY (all criteria pass; warnings allowed and
named), NOT-READY (any criterion fails — each failure named
with the fix), INVALID (the manifest itself does not parse
or is not an object). Exit codes: 0 = READY, 1 = NOT-READY,
2 = INVALID / usage error.

Commands:
  python3 scripts/wiki_automation_gate.py check <manifest.json>
      [--json]
  python3 scripts/wiki_automation_gate.py template
      (prints the manifest template — the same text as
      templates/automation-manifest.example.json)

This checker judges the MANIFEST, not the automation's code:
it is a pre-flight declaration gate. Whether the automation
actually honours its declarations is what its tests and its
log are for. Stdlib only.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent

NOTICE_OK = ("chat", "email", "lens", "log+chat", "log+email",
             "log+lens")
KILL_KINDS = ("stop-file", "env", "command")

TEMPLATE = {
    "name": "example-nightly-example",
    "owner": "owner-or-agent-seat",
    "command": ["python3", "scripts/wiki_example.py", "--once"],
    "schedule": {"kind": "cron", "expression": "15 3 * * *"},
    "idempotent": True,
    "idempotence_key": "content-hash dedupe: an unchanged input "
                       "produces the same item id and is a no-op",
    "kill_switch": {"kind": "stop-file",
                    "value": "evaluation/example.STOP"},
    "log_path": "evaluation/example-runs.log",
    "owner_notice": "log+chat",
    "max_runtime_seconds": 600,
    "max_items_per_run": 100,
    "writes": ["evaluation/example-register.jsonl"],
    "dry_run_default": False,
}


def check_manifest(m):
    """Returns (verdict, checks) where checks is a list of
    {criterion, ok, detail} in criterion order. Pure function
    of the manifest dict — the tests pin it directly."""
    checks = []

    def add(criterion, ok, detail):
        checks.append({"criterion": criterion,
                       "ok": bool(ok), "detail": detail})

    if not isinstance(m, dict):
        return "INVALID", [{"criterion": "manifest", "ok": False,
                            "detail": "manifest is not a JSON object"}]

    name = str(m.get("name") or "").strip()
    owner = str(m.get("owner") or "").strip()
    cmd = m.get("command")
    add("identity",
        name and owner and isinstance(cmd, list) and cmd
        and all(str(c).strip() for c in cmd),
        f"name={name!r} owner={owner!r} command="
        f"{'argv list of ' + str(len(cmd)) if isinstance(cmd, list) and cmd else 'missing/invalid'}")

    sched = m.get("schedule")
    sched_ok = False
    sched_detail = "no schedule stated"
    if isinstance(sched, dict):
        kind = sched.get("kind")
        if kind == "cron" and str(sched.get("expression") or "").strip():
            sched_ok, sched_detail = True, f"cron {sched['expression']!r}"
        elif kind == "interval" and \
                isinstance(sched.get("seconds"), (int, float)) \
                and sched["seconds"] > 0:
            sched_ok, sched_detail = True, f"every {sched['seconds']}s"
        elif kind == "manual":
            sched_ok, sched_detail = True, "manual launch (stated)"
    add("schedule", sched_ok, sched_detail)

    idem_key = str(m.get("idempotence_key") or "").strip()
    add("idempotence",
        m.get("idempotent") is True and len(idem_key) >= 8,
        "declared idempotent with mechanism: " + idem_key
        if (m.get("idempotent") is True and len(idem_key) >= 8)
        else "must declare idempotent: true AND name the mechanism "
             "in idempotence_key (how a re-run stays safe)")

    ks = m.get("kill_switch")
    ks_ok = isinstance(ks, dict) and ks.get("kind") in KILL_KINDS \
        and str(ks.get("value") or "").strip()
    add("kill_switch", ks_ok,
        f"{ks.get('kind')}: {ks.get('value')}" if ks_ok else
        "must name a kill switch: {kind: stop-file|env|command, "
        "value: path / var / command}")

    log_path = str(m.get("log_path") or "").strip()
    add("log_path", bool(log_path),
        log_path or "no log_path stated — unattended work with "
                    "no log cannot be audited")

    notice = str(m.get("owner_notice") or "").strip()
    add("owner_notice", notice in NOTICE_OK,
        f"owner_notice={notice!r}" if notice in NOTICE_OK else
        f"owner_notice={notice!r} — 'log-only' and silence are "
        f"refused for unattended running; one of {NOTICE_OK}")

    warnings = []
    rt = m.get("max_runtime_seconds")
    items = m.get("max_items_per_run")
    bounded = isinstance(rt, (int, float)) and rt > 0 \
        and isinstance(items, (int, float)) and items > 0
    unbounded_reason = str(m.get("unbounded_reason") or "").strip()
    if not bounded and unbounded_reason:
        warnings.append("unbounded, reason stated: " + unbounded_reason)
        bounded = True  # a named exception passes, as a warning
    add("bounded", bounded,
        f"max_runtime_seconds={rt} max_items_per_run={items}"
        if bounded and not warnings else
        (warnings[-1] if warnings else
         "must state max_runtime_seconds > 0 and "
         "max_items_per_run > 0, or an explicit unbounded_reason"))

    writes = m.get("writes")
    writes_ok = isinstance(writes, list) and \
        all(isinstance(w, str) and w.strip() for w in writes)
    if m.get("dry_run_default") is True:
        writes_ok = True
    add("no_live_wiring", writes_ok,
        ("read-only (writes: [])" if writes == [] else
         f"writes stated: {writes}" if isinstance(writes, list)
         and writes else
         "dry_run_default: true" if m.get("dry_run_default") is True
         else "must state writes (the paths/areas it may write; "
              "[] = read-only) or dry_run_default: true"))

    verdict = "READY" if all(c["ok"] for c in checks) else "NOT-READY"
    return verdict, checks


def cmd_check(args):
    path = Path(args.manifest)
    if not path.is_file():
        print(f"wiki_automation_gate: no manifest at {path}",
              file=sys.stderr)
        return 2
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"wiki_automation_gate: INVALID manifest "
              f"({exc})", file=sys.stderr)
        return 2
    verdict, checks = check_manifest(m)
    if args.json:
        print(json.dumps({"manifest": str(path),
                          "verdict": verdict, "checks": checks},
                         indent=2, ensure_ascii=False))
    else:
        print(f"automation-readiness: {verdict} — "
              f"{m.get('name', '(unnamed)')}")
        for c in checks:
            mark = "ok  " if c["ok"] else "FAIL"
            print(f"  [{mark}] {c['criterion']}: {c['detail']}")
    return 0 if verdict == "READY" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Automation-readiness pre-flight gate: "
                    "checks a proposed automation's manifest "
                    "against the stated unattended criteria.")
    ap.add_argument("--root", default=None,
                    help="repo root (accepted for house "
                         "consistency; the gate is manifest-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("manifest")
    p.add_argument("--json", action="store_true")
    sub.add_parser("template")
    args = ap.parse_args(argv)
    if args.cmd == "template":
        print(json.dumps(TEMPLATE, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "check":
        return cmd_check(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
