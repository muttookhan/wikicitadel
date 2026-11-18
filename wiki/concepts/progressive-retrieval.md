---
title: "Progressive retrieval — dual-level routing, layered disclosure, proposed lenses"
type: concept
status: draft
created: 2026-10-21
updated: 2026-10-21
sources:
  - raw/sources/founding-note.md
tags: [retrieval, search, marathon]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: synthesis
methods: Compiled from the harvest sketches for dual-level routing (LightRAG, MIT), the 3-layer progressive-disclosure read path (claude-mem, Apache-2.0) and the proposed-lenses pattern (exocortex, MIT); machinery built and fixture-tested in Marathon Round 3, lane TA1, against the fictional demo corpus only.
---

# Progressive retrieval

Three retrieval tools, all over the existing search machinery
(`scripts/wiki_search.py`) — no new ranker, and the measured
ranking is untouched.

## Dual-level routing

`scripts/wiki_dualroute.py` routes a query to page-level or
passage/chunk-level search by deterministic rules stated in the
code (R1–R8, first match wins, every decision records its rule):
an explicit `page:`/`passage:` prefix, a quoted phrase, a
dated/numbered term, an overview cue, a definition shape, a
pinpoint cue, a long qualified question — and, for a genuinely
ambiguous shape, `both`: both levels run and return labelled,
never silently merged. The dual-level shape is adapted from
LightRAG (HKUDS, MIT; EMNLP 2025).

## Three-layer progressive disclosure

`scripts/wiki_progressive.py` returns retrieval in layers a
caller can stop between: layer 1 compact index hits (path,
title, score), layer 2 page summaries (headings + verbatim
extractive summary), layer 3 full passages. Layers are
cumulative and monotonic — same hits, same order, same scores
at every layer — and each layer carries its visible cost
(chars and an approximate token count). The read-path design is
adapted from claude-mem (Apache-2.0); its session auto-capture
is not adopted.

## Proposed lenses from un-filed sources

`scripts/wiki_lens_propose.py` scans `raw/` for sources with no
compiled page (no wiki page's `sources:` names them, and no
`wiki/sources/` stem matches) and proposes a lens for every
group of at least two that share a tag — tags copied verbatim,
never synonym-merged — or a raw collection directory. Every
proposal carries `status: proposed`; the tool never auto-files
(with no `--out` it writes nothing at all), and a lens stands
only when the owner approves it. Pattern: exocortex (MIT).
