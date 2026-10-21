---
id: marathon-round-3-ta7-2026-10-21
title: "Marathon Round 3 — TA7: doors and watch machinery"
type: synthesis
status: current
created: 2026-10-21
updated: 2026-10-21
sources: [wiki/ideas.md]
tags:
  - build
  - mcp
  - automation
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: synthesis
methods: "Compiled by lane TA7 of Marathon Round 3 from the lane's own build record: the four tools below and their fixture tests, in the fictional demo corpus's terms."
---

# Marathon Round 3 — TA7: doors and watch machinery

Four Tier A rows over the wiki's doors and its standing watch
machinery, built 2026-10-21.

## 1. The MCP read door gains `--pin`

The traversal door's frozen read (`scripts/wiki_traverse.py
--pin <commit>`) now exists at the MCP read door
(`tools/mcp-read/server.py`) as a session default (`--pin` at
startup) and as a per-call `pin` argument on any of the eight
tools. Semantics are the traversal door's own, imported —
`resolve_pinned_root` verifies the commit and extracts its
tree read-only by git archive; the working tree is never
written, checked out, or moved. A pinned result is stamped
`pin: <resolved commit>`; an unpinned result is the old
shape exactly. An unresolvable pin is refused.

## 2. Per-page link-health in the Lens inspector

`scripts/wiki_link_health.py` computes, per compiled page,
broken wikilink targets (named), resolved and on-disk
non-page targets, inbound count, and orphan status —
resolution by the corpus's own precedence (path, stem,
title), the Quartz/LeafWiki per-page link-health pattern.
One computation renders both the report and the
Lens-inspector data file (`emit` → `link-health.json`,
keyed by page path); the Lens-build wiring is proposed in
the lane manifest rather than landed unilaterally.

## 3. The automation-readiness gate

`scripts/wiki_automation_gate.py` is the pre-flight checker
for any proposed unattended automation: a small JSON
manifest (template: `templates/automation-manifest.example.json`)
checked against stated criteria — identity, schedule,
idempotence with its mechanism NAMED, a kill switch, a log
path, owner notice (log-only is refused), stated bounds (or
a named unbounded reason), and a stated write surface.
Verdicts: READY / NOT-READY (each failure named with its
fix) / INVALID.

## 4. Gap-9 standing auto-watch (the auto-watch half)

`scripts/wiki_auto_watch.py` completes gap 9's standing
half. It watches the drop locations named in a watch
manifest (template: `templates/watch-manifest.example.json`)
and offers new arrivals to the EXISTING ingest queue through
the queue's own CLI — its content-hash identity, locking
and register are never re-implemented. A state file records
every offered file by content hash (atomic write, fsynced):
a restart re-offers nothing twice, a changed file is a new
arrival, a vanished file drops out of state, and a torn
state file is refused rather than silently reset. The
watcher's own automation block must pass the
automation-readiness gate before `run` starts, and its
stop-file kill switch ends the loop cleanly. It is NOT
wired into any live cron; a proposed cron line stands in
the lane manifest.
