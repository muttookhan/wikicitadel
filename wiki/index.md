# Index — the seed demo corpus

A minimal, fully fictional WikiCitadel installation. Every page below
exists to exercise a piece of the machinery: citations, a superseded and
severed claim, an owner attestation, a tombstone, and a ruling waiting
on the owner.

## Orientation

- [[overview]] — why this wiki exists, in the owner's own founding terms.
- [[decision-register]] — the founding decision pair: a blanket direction, and its same-day reversal for decisions.
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

## Sources

- [[founding-note]] — the founding dictation, preserved at `raw/sources/founding-note.md`.
