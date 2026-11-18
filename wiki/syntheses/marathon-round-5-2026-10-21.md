---
title: "Marathon Round 5 — record (2026-10-21)"
type: synthesis
created: 2026-10-21
updated: 2026-10-21
sources: []
tags: [marathon, record]
stage: seedling
planted: 2026-10-21
tended: 2026-10-21
work_type: record
methods: "Written from the artefacts: suite counts re-run in this tree after integration; lane manifests hash-audited against their scratch trees before any file was copied. This page is a build record; its claims are checkable against the code and tests in this tree."
---

# Marathon Round 5 — record (2026-10-21)

## Builds — six queued items

- **Web-fetch contract** (jina-ai/reader pattern,
  Apache-2.0): `scripts/wiki_fetch_contract.py` — a
  fetched page lands as one raw Markdown file with
  `kind: web-fetch`, the source URL, fetch date and the
  page's own title in frontmatter, and a `content_sha256`
  the checker recomputes — an edited body is a broken
  record. The fetcher is injectable; tests run offline.
- **BEIR zero-shot eval slice** (UKPLab/beir pattern,
  Apache-2.0): `evaluation/beir-tasks.json` registers
  three task definitions (nfcorpus, scifact, fiqa) —
  definitions and file layouts only, no dataset data in
  the tree, licences recorded as null with a note rather
  than inferred — and `scripts/wiki_beir_eval.py` scores
  runs on nDCG / Recall / MRR, deterministic under ties.
- **RO-Crate sidecar** (ro-crate-py pattern,
  Apache-2.0): `scripts/wiki_ro_crate.py` generates and
  checks `ro-crate-metadata.json` for any export bundle;
  regeneration is byte-identical, and a BagIt bag with a
  crate added still validates VALID (tested).
- **Corpus-generated eval questions** (Giskard RAGET
  pattern, Apache-2.0): `scripts/wiki_eval_draft.py`
  drafts questions deterministically from compiled pages,
  only where the expected answer occurs verbatim in the
  page. Drafts land ONLY under `staging/eval-drafts/`,
  stamped draft / unapproved; the tool refuses
  `evaluation/` paths, `golden-questions` names and
  overwrites, and hash-tripwires the golden set on every
  run. There is no promotion path in the tool.
- **FActScore atomic-claim check** (Min et al. pattern):
  `scripts/wiki_factscore_check.py` decomposes a page
  into atomic claims and verifies each at its own
  citation — presence, resolvability, range, then
  cited-text lexical support. It is report-only: it never
  edits a page and never marks one verified; every report
  carries `auto_verified: false`. The verification level
  is deterministic (no model calls) and is stated on the
  report's face.
- **Reflexion post-failure notes** (Shinn et al.,
  CC BY 4.0): `scripts/wiki_reflexion.py` composes a
  structured note — what failed, a cause class from a
  fixed vocabulary, the evidence record, the fixed
  do-differently action — appended only by an explicit
  `--apply` (dry-run by default, append-only). Its
  `scan` reads the failure registers where they exist
  and writes nothing. Notes are records, never silent
  behaviour changes.

The three conventions are also recorded in `AGENTS.md`
(eval drafts, atomic-claim check, reflexion notes).

## Verification (this tree, after integration)

scripts **1503 OK** (skipped=2); ask **274 OK**; gateway
**91 OK**; mcp-read **52 OK**; editor **56 OK**; Lens
**31 OK**; validator **PASS**; golden set byte-identical.
The model router remains an unwired seam.
