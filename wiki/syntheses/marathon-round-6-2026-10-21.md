---
title: "Marathon Round 6 — record (2026-10-21)"
type: synthesis
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [marathon, record]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
methods: "Written from the artefacts: suite counts re-run in this tree after integration; lane manifests hash-audited against their scratch trees before any file was copied. This page is a build record; its claims are checkable against the code, tests and registers in this tree."
---

# Marathon Round 6 — record (2026-10-21)

## Builds — seven queued items

- **CommonMark dialect pin + conformance**: the dialect
  is pinned as data in `evaluation/markdown-dialect.json`
  (CommonMark 0.31.2, CC BY-SA 4.0) and declared in
  `AGENTS.md`; `scripts/wiki_markdown_dialect.py` checks
  the pin and runs a 29-case attributed subset of the
  spec's own examples against the Lens renderer as a
  standing test. **Result: 15 of 29 cases pass; 14
  divergences are recorded with their observed output**
  in `evaluation/commonmark-conformance.json`, and the
  test asserts that set exactly — a new divergence fails,
  and a healed one fails until the record is updated.
  The renderer was not changed; the divergences are
  findings. Pipe tables are declared a local extension,
  not CommonMark.
- **RFC 7763 variant label**: served/exported Markdown
  declares `text/markdown; variant=CommonMark` — in the
  RO-Crate sidecar's per-file `encodingFormat` for `.md`
  files and in the Lens build manifest; the dialect
  check cross-verifies the sites agree.
- **MTEB task definitions**: `evaluation/mteb-tasks.json`
  registers a reranking task (SciDocsRR shape) and a
  multilingual JA/KO retrieval task (MrTIDI shape) in
  MTEB vocabulary — definitions only, no dataset data,
  licences recorded as null with a note.
- **PosQ positional-bias slice**: `evaluation/posq-slice.json`
  + `scripts/wiki_posq_check.py` run the same query with
  its passage at start/middle/end of a long carrier
  through the real ranker. **No collapse (ranks 2/1/3,
  score ratios 1.0/1.0/0.80) — but a real end-position
  penalty**, traced to the stage-4 lead-coverage rerank,
  is pinned as a tripwire assertion. The ranker was not
  retuned.
- **FAIR reuse statement**: frontmatter `reuse:` with a
  four-class vocabulary in `evaluation/reuse-vocabulary.json`
  (open / cite-only / internal / closed) and a
  report-only lint, `scripts/wiki_reuse.py`. The default
  for undeclared pages is this tree's configured `open`;
  the configuration warns that an installation replacing
  the seed corpus must restate it. No pages were
  backfilled — declaring is a compile act.
- **ORKG quality track**: frontmatter `quality_track:`
  (curated / automatic) beside the existing axes, a
  stated derivation rule for pre-existing pages, and
  `scripts/wiki_quality_track.py`, whose lint
  expectations differ by track (curated → citation
  correctness; automatic → completeness). Report-only.
- **Domain-analysis preamble**: an `AGENTS.md` section +
  `templates/section.md` — community, genres and
  terminology are named in writing before a new
  section's page types are chosen. Process text; no
  tooling, by design.

## Verification (this tree, after integration)

scripts **1541 OK** (skipped=2); ask **274 OK**; gateway
**91 OK**; mcp-read **52 OK**; editor **56 OK**; Lens
**36 OK**; validator **PASS**; golden set byte-identical.
The model router remains an unwired seam.
