---
title: "Marathon Round 8 — record (2026-10-21)"
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

# Marathon Round 8 — record (2026-10-21)

## Builds — twelve queued items

- **Model-identity provenance**:
  `scripts/wiki_model_provenance.py` + optional
  generator/verifier model flags on the verification
  recorders — new lines only; same-model lines are
  stamped report-only so self-verification is visible
  on the record.
- **Coverage-at-accuracy battery reporting**: the
  abstention battery's report now states the
  answered/abstained split and accuracy-on-answered
  beside pass/fail. Reporting only; the battery file
  and its thresholds are untouched.
- **Rosenthal threat-and-disclosure register**:
  `evaluation/threat-register.jsonl` +
  `scripts/wiki_threat_register.py` — nine threat
  classes mapped to stated strategies and their
  evidencing artefacts. Two classes — economic and
  organisational failure — are left blank as genuine
  findings: no stated strategy exists, and none was
  invented to fill the register.
- **Weighted snapshot damage field**: snapshot bundle
  records carry a per-class weighted missing/damage
  field beside the count; existing bundles gain it via
  a read-only report, never a rewrite.
- **WARC source capture**: `scripts/wiki_warc_capture.py`
  writes WARC 1.1 records whose payload digest is the
  hash the citation lockfile locks to (stdlib only; the
  earlier WARC 1.0 archiver untouched).
- **in-toto checkpoint attestation (pilot)**:
  `scripts/wiki_checkpoint_attestation.py` — a signed
  layout naming authorised agents per step, with
  hash-chained links from source hashes to compiled-page
  hashes, additive beside the checkpoint path. The pilot
  signature is an HMAC stand-in that proves the
  machinery's shape; it is labelled as such and is not
  the checkpoint path's SSH guarantee.
- **Difftastic adoption**: `scripts/wiki_review_diff.py`
  uses the external structural diff driver when present
  and degrades to a stated fallback diff when absent;
  no gate depends on it.
- **Identifier validation**: `scripts/wiki_pid_check.py`
  (DOI / ARK / ORCID / Handle / URN) as a standalone
  checker — the lockfile records carry no PID fields
  today, a fact the checker itself reports.
- **PPI judge reporting**: `scripts/wiki_judge_ppi.py`
  reports judge scores as estimate + interval + measured
  accuracy + labelled-n. At labelled-n 0 — the shipped
  register's state — it emits no estimate and says so.
- **CRUD lifecycle task definitions**:
  `evaluation/crud-lifecycle-tasks.json` — Create / Read
  / Update / Delete eval classes in this wiki's
  vocabulary, definitions only.
- **RAGBench sentence-support row schema**:
  `evaluation/ragbench-row-schema.json` + a row
  validator; the external dataset was not imported.
- **Annotation guidelines as data**:
  `evaluation/guidelines-settings.json` records each
  evaluation dataset's labelling guidelines as a named,
  versioned field. Current coverage is honestly 0: no
  dataset yet carries adopted guidelines, and the
  register says so per file rather than implying
  otherwise.

## Verification (this tree, after integration)

- Scripts **1648 OK** (skipped=2); ask **274 OK**;
  gateway **91 OK**; mcp-read **52 OK**; editor **56 OK**;
  Lens **42 OK**; validator **PASS** (rc=0); golden set
  byte-identical (`800e6c32…`). Model router
  byte-identical and unwired.
