---
title: "Compilation template — paper"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [templates, compilation]
template_for: paper
required_frontmatter: [title, type, created, updated, sources, tags]
required_sections: [## Summary, ## Claims, ## Evidence, ## Conditions and limits, ## Connections]
---

# Compilation template — paper

The section grammar a compiled page for a scholarly paper
(source page, `type: source`) must follow. Conformance is
checked by `scripts/wiki_compile_check.py check PAGE --type
paper`. A template is a starting shape: extra sections are
allowed; required sections may not be dropped or reordered.

## Summary

What the paper is, who wrote it, when, and where it was
published — one short paragraph.

## Claims

The paper's checkable claims, each with its inline claim
citation to the raw record.

## Evidence

The evidence the paper itself offers for its claims
(data, method, sample), stated as the paper states it.

## Conditions and limits

The conditions, limits and scope the paper states for its
claims (caveat carriage — omit this section only when the
paper states none, and say so in the Summary).

## Connections

Pages this paper updates, supports, or contradicts.
