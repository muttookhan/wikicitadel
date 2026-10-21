---
id: capture-pipeline-extensions
title: Capture pipeline extensions (Marathon Round 3, TA4)
type: concept
status: draft
created: 2026-10-21
updated: 2026-10-21
sources: ["raw/sources/founding-note.md"]
tags:
  - founding
work_type: record
stage: planted
---

# Capture pipeline extensions (Marathon Round 3, TA4)

Seven Tier A additions to the capture/ingest pipeline, built
2026-10-21 as seams onto the existing converter, clip and
capture tools — no second pipeline anywhere. (Demo-corpus
note: the examples below use the fictional sites and pages of
this edition's demonstration material.)

## Parse-quality gating (KR-R2)

`scripts/wiki_convert.py` scores every conversion
(`parse_quality`: readable ratio, token diversity, structure,
substance, garble penalty) and records the score in the
ingest sidecar's `parse_quality` block. With
`--quality-threshold`, a below-threshold parse is refused and
quarantined under `quarantine/parse-quality/` with its
report, exit code 3 — never filed. Pattern: TEDS-style
structural gating (idea only).

## Ingest buffer / flush batching (Memobase pattern)

`scripts/wiki_ingest_buffer.py` stages items into
`staging/ingest-buffer/` (payload first, entry JSON by atomic
rename) and flushes the batch through the existing clip path.
A flush claims an entry by rename and retires it only after
its draft is staged; a killed flush loses nothing — claimed
entries are recovered on the next run, and an entry whose
draft already exists is retired as already-flushed.

## Clip templates auto-selected by URL pattern

`scripts/wiki_clip_templates.py` is a registry of extraction
profiles keyed by URL patterns (reference-wiki, docs,
article), tried in order, with the **generic template as the
stated fallback** (fallback is recorded, never silent). A
tree may override entries via `templates/clip-templates.json`.

## Preview-and-edit capture checkpoint (MarkDownload pattern)

`wiki_clip.py --preview` stages a draft in
`staging/previews/` marked `capture_state: preview-unfiled`.
It is a filed capture only after
`scripts/wiki_preview.py confirm` moves the (possibly
edited) preview into `staging/captures/`, flips the state
line and leaves a receipt hashing the edited bytes as filed.
Discard moves a preview aside; nothing is deleted.

## Per-site extraction rules (wallabag pattern)

`templates/site-rules.json` carries one rule per domain
(keep/strip/title selectors in a small selector vocabulary),
consumed by `scripts/wiki_site_rules.py`: a matching rule
merges into the selected clip template's profile, the rule's
keep/title win, strips union, and the sidecar records which
rule fired and which strips actually matched — a rotted rule
is visible. Ships with documented example rules.

## The `jot` capture kind (Memos pattern)

`wiki_capture.py` gains the `jot` kind
(`templates/capture/jot.md`): a one-line quick capture — the
title is the line, provenance is the invocation's only or a
TODO prompt, never faked. It renders the same schema
frontmatter (sensitivity TODO, empty compile stamp) as every
kind and waits in `staging/captures/` like the rest.

## Suggested filing at ingest (DEVONthink Classify, Tier A half)

`scripts/wiki_suggest_filing.py` suggests a destination for
an item from title/tag token similarity over `wiki/index.md`
(title hits weigh 2, summary hits 1, tag hits 3) and the
clip path records the top suggestions in each sidecar. It is
a suggestion seam only: the tool has no write path, never
files anything, and an empty overlap is an honest empty
result. The heavier classifier half is a separate Tier B row.
