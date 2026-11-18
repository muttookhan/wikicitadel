---
title: "Landscape research — weekly run (2026-10-27)"
type: synthesis
created: 2026-10-27
updated: 2026-10-27
sources:
  - raw/sources/2026-10-27-landscape-weekly.md
  - raw/sources/2026-10-27-landscape-weekly.ingest.json
tags: [landscape, research]
stage: budding
planted: 2026-10-27
tended: 2026-10-27
work_type: synthesis
methods: Primary-source pass — GitHub API (repos + releases) read 2026-10-27 for the tracked landscape projects, arXiv abstract pages opened in full for four October 2026 papers, vendor blogs/release notes opened in full; search used for discovery only. Full record in the raw source; this page is its compiled digest.
---

# Landscape research — weekly run (2026-10-27)

## The headline

**The field's centre of gravity moved from remembering to forgetting.** Three arXiv papers posted 13–15 Oct 2026 (Bemula, Keep Your Receipts, Beyond Downstream QA) and a fourth on 21 Oct (MemoryTax) converge: what a memory system records at write time — provenance, per-claim receipts, the writer's identity — decides whether it can ever forget, supersede or clean up correctly. That is WikiCitadel's home ground (severance by register lookup, citation lockfile, treatment register, model-identity provenance), and this run turned the sharpest external test into a standing battery (§ Built).

## Tracked-project deltas since 2026-10-20 (GitHub API, point-in-time 2026-10-27)

- **New releases:** nashsu/llm_wiki **v0.6.13** (2026-10-22; 21,019★; no release notes in the body — no feature claims taken); Graphify **v0.9.94–v0.9.96** (Oct 22–26; 136,583★); claude-obsidian **v3.0.0/v3.0.1** (2026-10-21; 15,874★; hardening — recoverable transactions, offline labelled retrieval eval); obsidian-second-brain **v0.19.0 "The Check-In"** (Oct 24) and **v0.20.0 "The Batch"** (Oct 25) (4,965★; stale-note check-ins, quote-verified contradiction handling, resumable batch ingestion); Cognee **v1.6.6rc1** (Oct 23; history controls — dataset delete purges history and *fails if the purge cannot complete*); Basic Memory **v0.24.0/v0.24.1** (Oct 23; fix-dominated); AnythingLLM **v1.19.0** (Oct 26; not memory-relevant).
- **No new release:** Mem0, LightRAG, Khoj, Microsoft GraphRAG, Graphiti, qmd, llm-wiki-compiler, Letta (latest releases Sep 2026 or earlier; Graphiti v0.31.2 and llm-wiki-compiler 1.5.0 were recorded in the 2026-10-20 pass).
- **New to the tracked landscape: OceanBase PowerContext** (Apache-2.0, 1,378★) — v1.3.0 (Oct 12), v1.4.0 (Oct 19), v1.4.1 (Oct 26). Atomic memories with immutable revisions and exact evidence references; **forget = deactivate while retaining content and history, retired = cannot be restored directly**; a four-mode evidence gate (disabled/shadow/advisory/enforcing, default shadow); proposal-review "Dream" revisions that are never self-approved. An independent industrial corroboration of the tombstone/severance and proposal-machinery designs.

## The papers (all opened at arXiv)

- **Bemula** (Xie et al., arXiv:2610.18052, 13 Oct): first memory-unlearning benchmark — **no system passes more than 1.5% of forget requests end to end**, failing by leaving data extractable or by deleting too much. → Built (§ Built).
- **Keep Your Receipts** (Choudhary, arXiv:2610.17719, 13 Oct): direct-fact-only retraction cleanup cuts contaminated queries just 32.2% → 28.0%; per-artifact evidence receipts fix it, and **one receipt per sentence is 100%/88% faithful** vs about one-third for flat whole-text summary receipts.
- **Beyond Downstream QA** (Toma et al., arXiv:2610.22209, 15 Oct): FEB-30 — intrinsic vs QA evaluation diverge 16 points; memory-operation classification correct **only 20%** of the time, invisible to QA-only eval.
- **MemoryTax** (Peng, arXiv:2610.29823, 21 Oct): designed memory's ceiling is set by the model that *wrote* it (one LoCoMo conversation; limits stated in the paper).
- **Memora / FAMA** (Uddin et al., Findings of ACL 2026, arXiv:2604.20006): forgetting-aware accuracy penalising reliance on invalidated memory.
- **Zep v4** (vendor blog, 2026-10-14): Ingestion Traces, `reference_time`, bounded expansion returning `truncated` + reason — the same explicit-omissions discipline the evidence pack here carries.

## Conditions and limits

Star counts and release states are point-in-time (2026-10-27) and drift. Paper results are the authors' own, on their stated corpora. A secondary aggregator's 2026-10-26 "Graph-MIND" launch claim is recorded in the raw source as **unverified** — no matching primary repository found; nothing adopted from it.

## Built

**The forgetting battery**: `scripts/wiki_forgetting_check.py` + `evaluation/forgetting-battery.jsonl`, with the convention recorded in AGENTS.md ("Forgetting battery"). Bemula adapted to deactivation-by-severance: for every severance entry — STORED (page still exists), SEVERED (usable cues), PARAPHRASE (reworded probe still matches the QUERY-match rule); for named controls — PRESERVATION (exists, not severed). First run in this tree: **2 entries, 11 checks, 0 failures**; unit tests 6/6.
