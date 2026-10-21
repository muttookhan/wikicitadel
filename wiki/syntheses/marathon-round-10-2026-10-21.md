---
title: Marathon Round 10 — record (2026-10-21)
type: synthesis
status: current
created: 2026-10-21
updated: 2026-10-21
tags: [marathon, round-10, record]
---

# Marathon Round 10 — record (2026-10-21)

**Research:** 24 fresh finds (semantic web / knowledge graphs;
local-first software) + deep-dive batch 7 (collaboration &
multi-writer, 15 judged). Deep-study counters seeded on the
register: projects 751/4,000, papers 260/1,000, university
research 19/1,000 (a verifiable floor).

**Builds — the twelve Round-8 Tier A items, all closed:**
OpenRefine and Bolognese bench trials ran with evidence
(operation history; before/after diffs); CiteIndex evidence
gate (report-only — first report: 0 public changes lacking
evidence); CSL-JSON bibliography export (the citekeys register
holds zero citekeys, so the export is an empty list by fact);
Crossmark updates manifest (1 public update); CiteProof
checker-accuracy ledger (catches 3/3 seeded-bad fixtures,
controls 2/2, the real lockfile never touched); retraction-
propagation audit register; citation-function register (2 of 6
seeded entries classified, 4 honestly unclassified); CETEIcean
prototype ran on a labelled fixture; Annotorious prototype ran
headless with its W3C shape checker; GROBID trial is an honest
door failure (no Java runtime in the environment; the build
distribution download stalled — exact commands and errors in
`evaluation/grobid-trial-evidence.json`); the kraken OCR trial
is a door failure at install (its dependency stack did not
finish downloading in this environment; no OCR output exists —
`evaluation/kraken-trial-evidence.json`).

**Verification:** scripts **1730 OK (skipped=6)**, ask 274,
gateway 91, mcp-read 52, editor 56, Lens 42; validator **PASS**
(errors=0). Golden set byte-identical (`800e6c32…`). One
non-reproducing suite flake was observed during a /tmp-full
incident on the build VM; both full suites ran clean
end-to-end afterwards.

**Queue:** Round 9's nine Tier A items remain at the front,
followed by Round 10's eight.
