---
title: "Compilation template — transcript"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [templates, compilation]
template_for: transcript
required_frontmatter: [title, type, created, updated, sources, tags]
required_sections: [## Summary, ## Participants, ## Claims, ## Decisions and commitments, ## Connections]
---

# Compilation template — transcript

The section grammar a compiled page for a transcript
(conversation, meeting, export) must follow. Checked by
`scripts/wiki_compile_check.py check PAGE --type transcript`.

## Summary

What the conversation was, when it happened, and what it
was for — one short paragraph.

## Participants

Who took part, under the names the transcript itself uses.

## Claims

Checkable claims made in the transcript that the wiki
relies on, each cited to the raw record with its line
range (who said it is part of the claim).

## Decisions and commitments

Decisions taken and commitments given in the transcript,
verbatim where the pin rule applies; "none stated" when
there are none — never inferred.

## Connections

Pages this transcript updates, supports, or contradicts.
