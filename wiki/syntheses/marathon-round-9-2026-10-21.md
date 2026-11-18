---
title: "Marathon Round 9 — record (2026-10-21)"
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

# Marathon Round 9 — record (2026-10-21)

## Builds — ten queued items

- **Vocabulary basis lines**: `scripts/wiki_vocab_basis.py`
  renders the `basis:` for governed-vocabulary
  assignments from the vocabulary's own basis text, and
  checks for assignments lacking one.
- **LongMemEval knowledge-update + temporal slice**:
  `evaluation/longmem-update-temporal.json` +
  `-cases.jsonl` — a separate slice in the extended-set
  family (definitions, schema, fixture cases). The
  pinned abstention battery is untouched.
- **Job-run reliability line**: `scripts/wiki_job_reliability.py`
  computes pass^k-style repeated-run reliability over
  the `evaluation/job-runs.jsonl` register (defined as
  data, seeded empty-but-valid; populating it is
  operational use).
- **MAST failure-mode field**: a closed 14-mode
  vocabulary in this wiki's own words
  (`evaluation/mast-failure-modes.json`) with an
  additive sidecar beside the corrections ledger; the
  ledger itself is never rewritten, and unclassified
  entries are reported as unclassified.
- **Pre-action failure-history precheck**:
  `scripts/wiki_precheck.py` — before editing a
  page/path, one report surfaces its logged issues,
  failed attempts and fixes. Report-only.
- **Citeproc trial + CITATION.cff**:
  `scripts/wiki_citeproc.py` renders the citation
  lockfile into a formatted bibliography
  (`evaluation/citeproc-trial.md`, a derived artefact);
  `scripts/wiki_cff.py` generates/validates the
  CITATION.cff shape. **This tree's `CITATION.cff`
  carries public repository facts only and is
  deliberately not yet CFF-valid: the `authors` field
  is the project owner's credit decision and was not
  invented** (see `CITATION.cff.OWNER-NOTE.md`).
- **Placeholders report + link-reference export**:
  `scripts/wiki_placeholders.py` reports dangling
  links to never-created pages (first read: none);
  `scripts/wiki_link_refs.py` adds a default-off
  `--link-refs` option to the export path so exports
  stay navigable without wikilink tooling.
- **Kopia pilot — restore verified**: the Apache-2.0
  snapshot tool snapshotted a copy of this tree and
  restored it separately; 1,307 of 1,307 non-.git
  files were hash-identical after restore. Evidence
  and protocol: `evaluation/kopia-pilot-evidence.json`,
  `evaluation/kopia-pilot-protocol.md`. The pilot copy
  was a side-copy only; it changes nothing about what
  counts as the backup of record.
- **Heed-rate reporting**: `scripts/wiki_heed_rate.py`
  + the additive `evaluation/correction-outcomes.jsonl`
  register. The first report is honestly "unmeasured" —
  no outcome has been recorded for any existing
  correction, and none was invented. (This seed corpus
  has no corrections-ledger page yet, so the report
  cannot run here; the machinery stands ready.)
- **Reproducibility grading + traced-or-null**:
  `evaluation/bench-reproducibility.json` records each
  benchmark/eval dataset's reproducibility level and
  enforces traced-or-null on externally sourced fields.
  Every record currently stands ungraded (null),
  stated plainly.

## Verification (this tree, after integration)

- Scripts **1704 OK** (skipped=6 — by-design skips for
  registers this tree does not carry); ask **274 OK**;
  gateway **91 OK**; mcp-read **52 OK**; editor **56 OK**;
  Lens **42 OK**; validator **PASS** (rc=0); golden set
  byte-identical (`800e6c32…`). Model router
  byte-identical and unwired.
