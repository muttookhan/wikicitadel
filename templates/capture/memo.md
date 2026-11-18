---
title: "%:title"
capture_kind: memo
captured: %U
capture_date: %:date
captured_by: %:by
provenance: %a
destination: %:destination
status: draft
confidence: observed
sources: []
tags: %:tags
# TODO (capture) — sensitivity: answer before ingest. One of
# public | internal | personal | family-sensitive | export-only |
# credential-adjacent (evaluation/sensitivity.json). While this
# line stands unanswered the draft is UNCLASSIFIED, and the
# ingest converter refuses unclassified material a home in raw/
# The compile stamp below stays empty for the same
# reason: a capture is not yet a compile.
sensitivity: TODO
compiled_prompt:
compiled_converter:
compiled_date:
---

<!-- CAPTURE TEMPLATE — memo (usememos/memos pattern, MIT —
     pattern only, our own code; Marathon Round 4). The
     timeline-inbox door: ONE timeline, and TAGS AS THE ONLY
     STRUCTURE — no folders, no categories, no hierarchy.
     The memo's tags ride in the frontmatter above, filled
     from the invocation's --tags; the store door is
     scripts/wiki_memo.py (add/list/timeline over
     staging/memos.jsonl), and the read doors (traverse
     `memos`, the MCP read door's wiki_memos) list the inbox
     from day one. Grammar as in the source-note template;
     the one designed prompt is Why. This draft waits in
     staging/captures/. -->

# Memo — %:title

**The memo:** %:title

**Tags:** %:tags

**Captured:** %U · **By:** %:by · **Provenance:** %a

## Why

%^{Why — the one designed prompt: what makes this worth keeping}
