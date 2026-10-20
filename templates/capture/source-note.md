---
title: "%:title"
capture_kind: source-note
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

<!-- CAPTURE TEMPLATE — source-note.
     Grammar (our own code, from the org-capture specification): the harness fills the timestamp, the date, the
     provenance link (the place capture was invoked from) and
     the keyword fields; the prompt marks stand only for what
     the harness cannot know; the cursor mark shows where
     writing starts. The artefact slots hold the thing captured
     (the initial-content role in org's grammar); the one
     designed prompt is Why. Named destination: wiki/sources/,
     compiled at ingest from the raw record — this draft waits
     in staging/captures/ and is not a wiki page. A template is
     a starting shape, not a fill-in-the-blanks obligation. -->

# %:title

**The thing read:** %^{the raw path, URL or identifier — the artefact itself, not a description of it}
**Author / origin:** %^{who made it, if the artefact does not say}
**Its date:** %^{the source's own date, if it carries one}

## Why

%^{Why — why this was read, and why it belongs in the wiki}

## The thing itself

%? %^{the captured content, or the pointer to where it landed in raw/ — verbatim where the pin rule applies (a reversal, a rejected alternative, a "pin this")}

## Claims it carries

%^{the claims this source will support — each with the conditions its source states for it; a claim compiled without its conditions overstates the source (caveat carriage)}

## Connections

- Updates / relates to: [[]]
- Contradicts: [[]]
