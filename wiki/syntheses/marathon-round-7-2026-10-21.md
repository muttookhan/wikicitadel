---
title: "Marathon Round 7 — record (2026-10-21)"
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

# Marathon Round 7 — record (2026-10-21)

## Builds — eight queued items

- **DocETL decomposition + gleaning**:
  `scripts/wiki_compile_decompose.py` +
  `evaluation/compile-decompose.json` — sources above the
  threshold stated as data are split before compilation
  with a gather block carrying context across the split;
  the glean pass runs the recorded per-class validation
  prompts as a deterministic checklist. Machinery only —
  a glean report never marks a page verified.
- **Lens citation augmentation (CiteSee pattern)**:
  a citation pairing shows reliance count, treatment and
  cited-text-changed state in place, computed from the
  existing lockfile / treatment / outcomes registers.
  Stated remainder: the changed state's date is wired
  through the API and tests but not yet computed
  per-source in the build; standing renders "changed"
  dateless rather than inventing a date.
- **Lens git provenance (Memoize pattern)**: every page
  artefact carries last-modified + last author from git
  and an edit link formed from the one configured prefix
  in `tools/lens/lens-config.json`.
- **Tracking-parameter stripping at capture**:
  `scripts/wiki_url_normalise.py` wired into the clip and
  snapshot paths — the recorded URL is normalised, the
  original preserved verbatim alongside it. Feed-clip
  item links deliberately not normalised (the feed
  register's seam).
- **textlint starter check**: rule config as data in
  textlint's shape (`evaluation/textlint-config.json`;
  no-todo + terminology against
  `evaluation/canonical-names.json`); the runner is this
  tree's own Python/stdlib `scripts/wiki_textlint.py` —
  report-only, optional, unwired.
- **The Jotter pattern** (re-implemented only — GPL
  pattern, no code copied): `scripts/wiki_jotter.py`
  (validate / cited-by / unconnected, all report-only) +
  the frontmatter `source_record:` shape declared in
  `evaluation/source-record-schema.json`. No backfill:
  the shape is the deliverable.
- **Feed-clip identity + tri-state register**:
  `scripts/wiki_feed_register.py` + append-only
  `evaluation/feed-clips.jsonl` — stable item identity,
  staged / dismissed / ingested states, `should-stage`
  consulted before staging, re-runnable per-feed cleanup.
  Deliberately unwired from the clip path; the one-call
  seam is documented.
- **Browser-bookmarks importer**:
  `scripts/wiki_bookmarks.py` reads a bookmark file it is
  handed (Chrome JSON / Firefox backup JSON / Netscape
  HTML), stages templated drafts into
  `staging/bookmarks/` only, deduped against
  `evaluation/bookmarks-register.jsonl`. Manual-first:
  no sync, no browser access, no fetching.

## Verification (this tree, after integration)

- Scripts **1586 OK** (skipped=2); ask **274 OK**;
  gateway **91 OK**; mcp-read **52 OK**; editor **56 OK**;
  Lens **42 OK**; validator **PASS** (rc=0); golden set
  byte-identical (`800e6c32…`). Model router
  byte-identical and unwired.
