---
title: "%:title"
capture_kind: idea
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

<!-- CAPTURE TEMPLATE — idea.
     An undirected idea waits for the owner's call: at
     integration the Waiting line below is appended to
     wiki/ideas.md under "Waiting for your call", and nothing
     is built until the owner rules — silence is not approval (the
     ask-first rule). Grammar as in the source-note template;
     the one designed prompt is Why. This draft waits in
     staging/captures/; it is not yet on the board. -->

# Idea — %:title

**The Waiting line (one line, as it will stand on [[ideas]]):** %:title — %:by, %:date

## Why

%^{Why — what problem this solves, or what it makes possible}

## The idea

%? %^{one short paragraph: enough for the owner to rule on, no more}
