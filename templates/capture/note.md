---
title: "%:title"
capture_kind: note
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

<!-- CAPTURE TEMPLATE — note.
     The session observation: the grey-zone capture the
     [[capture-rules]] govern — something measured or verified
     (trigger 4), a commitment given (trigger 5), a remark that
     judgement alone used to decide. When a candidate matches
     the do-not-record list, the list wins and this draft is
     discarded, not filed. Grammar as in the source-note
     template; the one designed prompt is Why. Named
     destinations: wiki/filings/, or the page the note touches,
     plus wiki/log.md — all at integration; this draft waits
     in staging/captures/. -->

# Note — %:title

**Observed:** %U · **By:** %:by · **Provenance:** %a

## What was observed

%? %^{the concrete thing: a measurement carries its value, its date and the instrument or method that produced it; a commitment names who owes what by when; anything else, short and concrete}

## Why it is filed

%^{Why — which capture trigger this matches, or why judgement files it anyway}
