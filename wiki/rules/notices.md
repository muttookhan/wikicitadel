---
id: notices
title: Notices — the rules page
type: synthesis
status: current
created: 2026-01-15
updated: 2026-01-15
sources: []
tags:
  - governance
work_type: record
methods: "Generated from evaluation/notice-vocabulary.json so the fixed texts quoted here are verbatim by construction."
stage: tended
---

# Notices — the rules page

A Notice is a fixed-text label applied to a page whose standing needs a visible
caution. The wording lives only in `evaluation/notice-vocabulary.json`; a page
carries the block verbatim, never a paraphrase, and a notice is retired only by
an owner ruling recorded in `evaluation/notices.jsonl`. This page quotes the
vocabulary so a reader can check any block against the text of record.

## source-integrity-questioned — Source integrity questioned

Mechanical: the page is a source page whose latest integrity grade in evaluation/source-grades.jsonl is 'questioned'.

> This page rests on a source whose integrity this wiki grades **questioned** in the source-grades register (`evaluation/source-grades.jsonl`): a specific assertion of that source stands unverified on the source's own terms. Read the page as a faithful account of what the source says, not as established fact, until the grade is resolved.

## claim-negative-treatment — Claim under negative treatment

Mechanical: evaluation/treatment-register.jsonl holds a treatment event with grade 'negative' whose subject.page is this page.

> At least one claim carried on this page has been treated **negative** in the treatment register (`evaluation/treatment-register.jsonl`): the claim as stated was superseded, reversed, or corrected, and it is severed from retrieval. The page keeps the claim visible, under this notice, because the record of what was believed is part of the evidence.

## personal-material — Personal material, owner-supplied

Stated rule: the page's frontmatter sources include material the owner supplied from their own records, marked personal in the source register.

> This page is compiled from personal material the owner supplied from their own records. It is held to the same citation standard as every other page, and it is classified personal: it does not leave this installation, and no export carries it without the owner's ruling.

## as-written-design — As-written design record — later decisions govern

Stated rule: a design or synthesis page preserved as written whose statements a later decision may have superseded.

> This page is a design record preserved **as written** on its date. Parts of it may state positions that later decisions have superseded; where this page and the decisions of record differ, the decisions govern. The page is kept verbatim because the history of the design is evidence, not because every sentence in it is current.

## attribution-incomplete — Attribution incomplete

Mechanical: a compiled page (type source/entity/concept/synthesis/query) whose frontmatter sources list is missing or empty.

> This compiled page cites **no sources**: the record it rests on is missing or was never attached. Its claims are unattributed on this wiki's own standard and should be treated as unverified until sources are attached and the page is re-compiled.
