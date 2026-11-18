---
title: "Marathon Round 3, Lane TA5 — proposal machinery (2026-10-21)"
type: synthesis
status: draft
created: 2026-10-21
updated: 2026-10-21
sources:
  - raw/sources/founding-note.md
tags: [marathon, proposals, graphify, sage-wiki, reme, lightmem, kr-r1, vanillaflava]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
methods: "Built in a scratch copy by lane TA5 under the Marathon Round 3 lane brief; every tool is deterministic stdlib Python, proposal-only, and pinned by fixture tests in scripts/tests/ using the fictional demo corpus."
---

# Marathon Round 3, Lane TA5 — proposal machinery

Six Tier A rows from the global-landscape harvest, all built
as PROPOSAL machinery: a tool may file a proposal for a
decision, and may never apply the change itself.

1. **Graphify — EXTRACTED-vs-INFERRED edge tags.**
   `scripts/wiki_graph_export.py` now stamps every exported
   edge with a `provenance` class: EXTRACTED for edges
   physically in a page (wikilink, frontmatter declaration,
   citation), INFERRED for tool-derived edges. Derived
   co-citation edges (two pages citing the same raw source)
   travel in their own `inferred_edges` list with the shared
   sources as evidence, never inflate the extracted census,
   and render dashed teal against the extracted edges' solid
   grey.
2. **sage-wiki — entity-resolution merge proposals.**
   `scripts/wiki_entity_merge.py` finds candidate duplicate
   entity pages (alias matches, name/stem similarity) and
   files merge proposals with evidence and a suggested
   survivor. It never merges.
3. **ReMe — compaction as a recoverable proposal.**
   `scripts/wiki_compact_proposal.py` drafts an extractive
   compaction of a long page as a filing artefact recording
   the original's SHA-256 and its restore path (the original
   is untouched; rejection restores the status quo exactly).
4. **LightMem — topic-segmented sleep-time consolidation.**
   `scripts/wiki_consolidate.py` groups uncompiled raw
   material by topic segment and files one consolidation
   proposal per segment — the nightly-sweep-shaped seam.
5. **KR-R1 — threshold-triggered compile proposals.**
   `scripts/wiki_compile_watch.py` files a compile proposal
   when an uncompiled raw source crosses a configurable
   age/size threshold, with a JSONL register of proposals
   (idempotent reruns).
6. **Vanillaflava — self-clearing Pending Review sections.**
   `scripts/wiki_pending_review.py` reads the stated entry
   grammar (`(status: resolved)` / `(expires: YYYY-MM-DD)`)
   and reports sections whose entries are all resolved or
   expired as clearable. Report-only; it never edits a page.

All six are pinned by fixture tests (25 tests) in
`scripts/tests/`, run in both trees.
