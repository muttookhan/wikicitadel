---
id: marathon-r3-tb8-patterns-2026-10-21
title: "Five gated patterns — build notes (demo corpus)"
type: synthesis
status: current
created: 2026-10-21
updated: 2026-10-21
sources: [wiki/ideas.md]
tags:
  - tools
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: synthesis
methods: "Build notes for machinery added to this demo codebase; each pattern was implemented in scoped form and pinned by fixture tests. No demo-corpus content is described beyond the tooling itself."
---

# Five gated patterns — build notes

Five patterns from the project's landscape research, built in
scoped, tested form. Every one is gated so its safe state is
the default state:

1. **Env-flagged destructive tools (Scrapbox MCP pattern).**
   `tools/gateway/gateway/destructive.py`: destructive-class
   tools are registered only when `WIKI_GATEWAY_ENABLE_DESTRUCTIVE`
   is exactly `true`; refusal is the default, and every invocation
   attempt — allowed or refused — is ledgered. The gateway ships
   no real destructive tool; a harmless fixture tool (deletes
   only inside a scratch directory) proves the gate.
2. **Workflow-as-MCP-tool (Langflow pattern).**
   `tools/mcp-read/workflows.py` + the `wiki_workflow` tool:
   a workflow definition (stated steps over the read door's eight
   read tools) is exposed as a single MCP tool. Registration
   rejects any non-read verb — the door gains no write verb.
   Built-ins: `census_and_cite`, `page_context`.
3. **Sandboxed verification scripts (E2B pattern).**
   `scripts/wiki_sandbox_run.py`: a verification script runs with
   a fresh temp cwd, a scrubbed environment, a timeout, and POSIX
   resource limits; the report states the sandbox's limits on its
   face — best-effort stdlib process isolation, not a security
   boundary, with network blocked only where `unshare -n` exists.
4. **Low-confidence web expansion (SearXNG pattern).**
   `scripts/wiki_web_expand.py`: takes a confidence value as
   input (it scores nothing); below threshold it proposes
   expansion queries. Fetching is an injectable seam, default
   OFF; results land only as UNFILED candidate sources with
   provenance, never auto-compiled.
5. **Narration plans (gap-15 remainder).**
   `scripts/wiki_narration_plan.py`, extending
   `scripts/wiki_audio_brief.py`: a narration PLAN as data — shot
   list, narration script, asset manifest — for image/video
   briefings. No media is generated and no external call is made.

A preset marketplace is out of scope by standing rule and was
not built.
