---
title: "Compilation template — repo"
type: concept
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [templates, compilation]
template_for: repo
required_frontmatter: [title, type, created, updated, sources, tags]
required_sections: [## Summary, ## Structure, ## Claims, ## Licence, ## Connections]
---

# Compilation template — repo

The section grammar a compiled page for a software
repository must follow. Checked by
`scripts/wiki_compile_check.py check PAGE --type repo`.

## Summary

What the repository is, whose it is, and what state it was
read in (commit / date).

## Structure

The layout that matters: entry points, main modules, and
where the behaviour a reader will ask about lives.

## Claims

Checkable claims the repo supports (what it does, how it
is licensed to behave), each cited to the raw snapshot.

## Licence

The licence as found in the repo itself, verbatim name and
where it sits — the field that decides idea-only vs
adaptable for anything taken from it.

## Connections

Pages this repo updates, supports, or contradicts.
