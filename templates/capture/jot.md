---
title: "%:title"
capture_kind: jot
captured: %U
capture_date: %:date
captured_by: %:by
provenance: %a
destination: %:destination
status: draft
confidence: observed
sources: []
tags: []
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

<!-- CAPTURE TEMPLATE — jot (Memos pattern, Marathon Round 3 /
     TA4). The lightweight door: ONE line, captured at the
     speed of thought. The title above IS the line — nothing
     else is required. Provenance is minimal by design: the
     invocation's %a, or the TODO prompt the grammar leaves
     when none was given; it is never invented after the fact.
     A jot is not a filing and not a note: at integration it is
     promoted to the kind it really is, or discarded under
     [[capture-rules]]. Grammar as in the source-note template;
     the one designed prompt is Why. This draft waits in
     staging/captures/. -->

# Jot — %:title

**The line:** %:title

**Captured:** %U · **By:** %:by · **Provenance:** %a

## Why

%^{Why — the one designed prompt: what makes this line worth keeping}
