---
title: "%:title"
capture_kind: decision
captured: %U
capture_date: %:date
decided: %:decided
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

<!-- CAPTURE TEMPLATE — decision.
     This template RECORDS a ruling; it never makes one —
     decisions are the owner's alone. Dual dating is structural
     here (governing rule 4): `decided` is the date the ruling
     was made, `captured` the date this record was written, and
     the two differ whenever a ruling is recorded after the
     fact. Named destinations: the decisions register, the
     human decision record, and wiki/log.md, all entered at
     integration — this draft waits in staging/captures/. A
     ruling not yet made is not a decision record: it is a
     proposal (templates/proposal.md, with its premortem) or an
     idea ([[ideas]]). Grammar as in the source-note template;
     the one designed prompt is Why. -->

# Decision — %:title

**Ruled by:** the owner
**Decided:** %:decided
**Recorded:** %U by %:by
**Provenance:** %a

## The ruling, verbatim

%? %^{the ruling in the owner's exact words — the pin rule: decisive words are copied verbatim, never merely summarised}

## Alternatives rejected

%^{what was offered or raised and not chosen — a decision whose rejected options are forgotten gets re-argued later as if it had never been taken}

## Why

%^{Why — the reason as stated, in the owner's words where the owner gave one}

## What it touches

%^{the pages, records and queues that relied on the old form and must be corrected on the record the same day (the reversal discipline, [[capture-rules]] trigger 2)}
