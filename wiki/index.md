# Index — the seed demo corpus

A minimal, fully fictional WikiCitadel installation. Every page below
exists to exercise a piece of the machinery: citations, a superseded and
severed claim, an owner attestation, a tombstone, and a ruling waiting
on the owner.

## Orientation

- [[overview]] — why this wiki exists, in the owner's own founding terms.
- [[decision-register]] — the founding decision pair: a blanket direction, and its same-day reversal for decisions.
- [[source-registry]] — generated catalogue of the raw source collections: per-collection counts and date span.
- [[ideas]] — the ideas board: waiting / approved / disapproved, ruled by the owner only.
- [[notices]] — the Notice vocabulary: fixed-text caution labels, quoted verbatim from `evaluation/notice-vocabulary.json`.
- [[evidence-ttl]] — the evidence TTL convention: evidence_as_of + evidence_ttl_days on a page, due-for-refresh reported by scripts/wiki_evidence_ttl.py; due is a re-check owed, never a deletion, and is not an owner attestation

## Entities

- [[owner]] — the installation's owner; an owner-attested page.

## Concepts

- [[standing-approval]] — tombstoned: the blanket form, retired with its reason stated.
- [[demo-guide-ja]] — the demo guide in Japanese: proof the seed corpus carries non-English pages natively.
- [[demo-guide-ko]] — the demo guide in Korean: the same proof, a second script family.
- [[memory-and-retrieval-designs]] — Six Tier B memory/retrieval designs built as machinery: loadout+visibility checker, claim diff-chains, L0/L1/L2 tiered reading, citation-gated advisory memory, groundedness gate (default off), append-only claim index with fusion ranking. (Marathon R3 TB2)
- [[progressive-retrieval]] — Progressive retrieval: dual-level routing (CN5b), 3-layer progressive disclosure (claude-mem) and proposed lenses from un-filed sources (exocortex); scripts/wiki_dualroute.py, wiki_progressive.py, wiki_lens_propose.py. (Marathon R3 TA1)
- [[capture-pipeline-extensions]] — Marathon Round 3 (TA4): parse-quality gating, ingest buffer/flush, URL-pattern clip templates, preview-and-edit checkpoint, per-site extraction rules, the jot capture kind, and suggested filing at ingest
- [[did-webvh]] — did:webvh recorded as a reading lead, not a build (2026-10-21).
- [[capture-triage-machinery]] — Capture and triage machinery: the ten capture/triage tools (filing router, rule-amendment detector, triage verdicts, companion groups, conversation-log query, snapshot bundles, OCR and transcription seams, staging inbox, citekeys) — all proposal/report/seam-shaped, nothing auto-applies.
- [[eval-judging-machinery-r3]] — Eval & judging machinery (R3 TB6): CRAG gate, MiniCheck fallback, LongMemEval template, quality gates, judge recovery, both-orders merge gate, judge-language A/B, native-eval gate, held-out hash manifest.
- [[marathon-round-3-ta7-2026-10-21]] — Marathon Round 3 lane TA7 (doors and watch machinery): the MCP read door's --pin frozen read, per-page link-health for the Lens inspector, the automation-readiness gate, and the gap-9 standing auto-watch in front of the ingest queue
- [[marathon-r3-ta5-proposal-machinery-2026-10-21]] — Marathon Round 3, Lane TA5 — proposal machinery (2026-10-21): Graphify EXTRACTED/INFERRED edge tags, sage-wiki merge proposals, ReMe compaction proposals, LightMem consolidation proposals, KR-R1 threshold compile proposals, Vanillaflava Pending Review checker; all proposal-only.
- [[marathon-r3-tb8-patterns-2026-10-21]] — Marathon Round 3 lane TB8: five gated patterns built (env-flagged destructive gateway tools, workflow-as-MCP-tool, sandboxed verification scripts, low-confidence web expansion, narration plans); gap-12 preset marketplace parked by gate.
- [[marathon-r3-tb7-retrieval]] — Retrieval and ranking machinery (Marathon R3, TB7): exact-title boost, ranking-expression evaluator, bounded graph expansion + GraphRAG community summaries, citation-scope checker, structured ingest register, KAG relation index, MemoRAG global memory, script normalization + Japanese dual-track profile, RAPTOR tree index, agent-object loader. Lens mirror data regenerates at Lens build.
- [[marathon-round-4-2026-10-21]] — the Marathon Round 4 record (2026-10-21): the fix round (citation lock 12/12, lifecycle warnings 19→0, ambiguous wikilinks 9→0, README corrected), memory-transparency views + TB4 Lens wiring, CJK segmentation, publish CLI, source catalogue, memo capture, schema extraction, memory distil, packing/MILU/reading-notes; suites 1456/274/91/52/56/31, validator PASS.
- [[marathon-round-5-2026-10-21]] — the Marathon Round 5 record (2026-10-21): six queued builds — web-fetch contract, BEIR task register, RO-Crate sidecar, corpus-generated eval-question drafts (staging only), the FActScore atomic-claim check (report-only), reflexion post-failure notes; suites 1503/274/91/52/56/31, validator PASS.
- [[marathon-round-6-2026-10-21]] — the Marathon Round 6 record (2026-10-21): seven queued builds — CommonMark pin + conformance test (15/29 pass; 14 divergences recorded, renderer unchanged), RFC 7763 variant label, MTEB task definitions, PosQ slice (no collapse; end-position penalty pinned), FAIR reuse statement, ORKG quality track, domain-analysis preamble; suites 1541/274/91/52/56/36, validator PASS.
- [[marathon-round-7-2026-10-21]] — the Marathon Round 7 record (2026-10-21): eight queued builds — DocETL decompose+glean, CiteSee Lens citation augmentation, Memoize git provenance, tracking-strip at capture, textlint starter check, Jotter pattern, feed-clip tri-state register, bookmarks importer; suites 1586/274/91/52/56/42, validator PASS.
- [[marathon-round-8-2026-10-21]] — the Marathon Round 8 record (2026-10-21): twelve queued builds — model-identity provenance, coverage-at-accuracy reporting, Rosenthal threat register (two classes blank as findings), weighted snapshot damage, WARC capture, in-toto pilot, Difftastic adoption, PID checker, PPI judge reporting, CRUD definitions, RAGBench schema, guidelines-as-data; suites 1648/274/91/52/56/42, validator PASS.
- [[marathon-round-9-2026-10-21]] — the Marathon Round 9 record (2026-10-21): ten queued builds — vocabulary basis lines, LongMemEval slice, pass^k run-log line, MAST failure-mode field, failure-history precheck, citeproc trial + CITATION.cff (owner-gated authors), placeholders report + link-reference export, Kopia pilot (restore verified), heed-rate reporting, reproducibility grading; suites 1704/274/91/52/56/42, validator PASS.
- [[marathon-round-10-2026-10-21]] — the Marathon Round 10 record (2026-10-21): Round 8's twelve Tier A items all closed (OpenRefine/Bolognese trials ran with evidence; GROBID and kraken trials are honest door failures); scripts 1730 OK, validator PASS, golden byte-identical.
- [[marathon-round-11-2026-10-21]] — the Marathon Round 11 record (2026-10-21): Round 9's nine Tier A items all closed; the Round 10 record page's missing sources field fixed (validator error at the R10 base); scripts 1764 OK, validator PASS, golden byte-identical.
- [[marathon-round-12-2026-10-21]] — the Marathon Round 12 record (2026-10-21): Round 10's eight Tier A items all closed; scripts 1824 OK, validator PASS, golden byte-identical; Rounds 11+12 published together as sync entry 26 after the publish-service outage.
- [[marathon-round-13-2026-10-21]] — the Marathon Round 13 record (2026-10-21): Round 11's ten Tier A items all closed; scripts 1868 OK, validator PASS, golden byte-identical; the publish-service outage and the local custody state stated plainly; 20 Tier A items stand boarded at programme close.
- [[curation-workarounds]] — the curation activities + workarounds register: an installation's own curation workarounds logged against Lee & Stvilia's activity structure as columns, in evaluation/curation-workarounds.jsonl via scripts/wiki_curation.py; seeded empty-but-valid, no workaround invented
- [[share-publish-cite-ready]] — the share / publish / cite-ready controlled vocabulary: three distinct states, with citability, quality control and ethical reuse as the test for publish; held as data in evaluation/share-publish-vocabulary.json, checked by scripts/wiki_publication_state.py

## Sources

- [[founding-note]] — the founding dictation, preserved at `raw/sources/founding-note.md`.
